import pygame
import math
import numpy as np
from RobotLib.Math import *


class Robot:
    """
    Maintains the state of the robot.
    
    Robot reference has x-axis pointing forward.
    Imaginary axle between wheels is oriented along y-axis; +y points toward left wheel.
    """

    def __init__(self):
        # constants for Sparki robot
        # from https://github.com/ArcBotics/Sparki/blob/master/Arduino%20Library/Sparki.h
        self.steps_per_rev = 4096
        self.wheel_diameter = 5.00  # cm
        self.track_width = 8.51  # cm
        self.steps_per_cm = self.steps_per_rev / (self.wheel_diameter * math.pi)  # steps/cm
        self.width = 9  # cm -- approximate
        self.length = 10  # cm -- approximate
        # conversion from step/sec to Sparki speed setting
        self.speed_per_step = 0.1
        self.sonar_offset = 2.5  # cm -- approximate distance from center of robot to sonar center

        # status variables
        self.requested_lin_vel = 0  # cm/s
        self.requested_ang_vel = 0  # rad/s
        self.lin_vel = 0  # cm/s
        self.ang_vel = 0  # rad/s
        self.x = 0  # cm
        self.y = 0  # cm
        self.theta = 0  # rad
        self.requested_sonar_angle = 0  # rad -- 0 angle = sonar pointed along x-axis of robot
        self.sonar_angle = 0  # rad -- 0 angle = sonar pointed along x-axis of robot
        self.sonar_distance = 10  # cm -- mean of the last 5 sonar distances
        self.sonar_distance_array = []  # cm -- last 5 sonar distances
        self.is_tile = 0  # 1 for tile, 0 for no tile
        self.gripper_status = 0  # gripper_status, 0 = stop, 1 = open, 2 = close
        self.line_left = 0  # left line sensor, 0 for no line, 1 for line
        self.line_center = 0  # center line sensor, 0 for no line, 1 for line
        self.line_right = 0  # right line sensor, 0 for no line, 1 for line
        self.compass = 0  # compass direction
        self.distance_threshold = 5 # in order to no detect distances lower than a distance

    def get_robot_map_transform(self):
        """ Get transformation that takes points from robot frame to map frame """
        return transform(self.x, self.y, self.theta)

    def get_map_robot_transform(self):
        """ Get transformation that takes points from map frame to robot frame """
        return invert(self.get_robot_map_transform())

    def get_sonar_robot_transform(self):
        """ Get transformation that takes points from sonar frame to robot frame """
        return transform(0, 0, self.sonar_angle) * transform(self.sonar_offset, 0, 0)

    def get_robot_sonar_transform(self):
        """ Get transformation that takes points from robot frame to sonar frame """
        return invert(self.get_sonar_robot_transform())

    def compute_motors(self):
        """Compute steps/sec for motors
           Returns:
              left motor speed, left motor direction,
              right motor speed, right motor direction
        """
        if self.requested_lin_vel == 0 and self.requested_ang_vel == 0:
            return 0, 0, 0, 0

        # compute linear velocities of left and right wheels in cm/s
        vel_l = self.requested_lin_vel - self.requested_ang_vel * self.track_width * 0.5
        vel_r = self.requested_lin_vel + self.requested_ang_vel * self.track_width * 0.5

        # compute wheel velocities in steps/s
        steps_per_sec_l = vel_l * self.steps_per_cm
        steps_per_sec_r = vel_r * self.steps_per_cm

        # compute speed and direction for each wheel
        left_speed = int(abs(steps_per_sec_l) * self.speed_per_step)
        right_speed = int(abs(steps_per_sec_r) * self.speed_per_step)
        left_dir = steps_per_sec_l > 0
        right_dir = steps_per_sec_r > 0

        # cap at 100
        if left_speed > 100:
            # print('warning: left speed hit max (%.2f lin, %.2f ang)'%(self.lin_vel,self.ang_vel))
            left_speed = 100
        if right_speed > 100:
            # print('warning: right speed hit max (%.2f lin, %.2f ang)'%(self.lin_vel,self.ang_vel))
            right_speed = 100

        # return settings
        return left_speed, left_dir, right_speed, right_dir

    def compute_velocities(self, left_speed, left_dir, right_speed, right_dir):
        """Compute angular and linear velocities from motor settings
        """

        # motor speeds in steps/s
        steps_sec_l = left_speed / self.speed_per_step
        if left_dir == 0: steps_sec_l = -steps_sec_l

        steps_sec_r = right_speed / self.speed_per_step
        if right_dir == 0: steps_sec_r = -steps_sec_r

        # wheel velocities in cm/s
        vel_l = steps_sec_l / self.steps_per_cm
        vel_r = steps_sec_r / self.steps_per_cm

        # compute linear and angular velocities
        self.lin_vel = (vel_l + vel_r) * 0.5
        self.ang_vel = (vel_r - vel_l) / self.track_width

    def get_T_motion(self, time_delta):
        if self.ang_vel == 0:
            # pure linear motion
            T_motion = transform(self.lin_vel * time_delta, 0, 0)
        elif self.lin_vel == 0:
            # pure rotational motion
            T_motion = transform(0, 0, self.ang_vel * time_delta)
        else:
            # move origin to ICC
            R = self.lin_vel / self.ang_vel
            T_motion = transform(0, R, 0)
            # perform rotation
            T_motion = T_motion * transform(0, 0, self.ang_vel * time_delta)
            # move origin back
            T_motion = T_motion * transform(0, -R, 0)
        return T_motion

    def update(self, time_delta):
        # get current transform
        T_robot_map = self.get_robot_map_transform()

        # perform motion
        T_motion = self.get_T_motion(time_delta)
        T_robot_map = T_robot_map * T_motion

        # extract new position and orientation
        self.theta = angle(T_robot_map)
        self.x = T_robot_map[0, 2]
        self.y = T_robot_map[1, 2]

    def draw(self, surf):
        """ Draw robot onto a surface """

        # calculate robot dimensions
        width = self.width
        length = self.length
        half_width = width * 0.5
        half_length = length * 0.5

        # get transformation from robot to map
        T_robot_map = self.get_robot_map_transform()
        T_sonar_robot = self.get_sonar_robot_transform()

        # get corners of robot in map frame
        center = mul(T_robot_map, vec(0, 0))
        left_front = mul(T_robot_map, vec(half_length, half_width))
        right_front = mul(T_robot_map, vec(half_length, -half_width))
        left_back = mul(T_robot_map, vec(-half_length, half_width))
        right_back = mul(T_robot_map, vec(-half_length, -half_width))

        # get sonar location in map frame
        sonar = mul(T_robot_map * T_sonar_robot, vec(0, 0))

        # get sonar ping location in map frame
        sonar_ping = mul(T_robot_map * T_sonar_robot, vec(self.sonar_distance, 0))

        # draw lines
        pygame.draw.line(surf, (0, 0, 0), center, sonar)
        pygame.draw.line(surf, (255, 0, 0), sonar, sonar_ping)
        pygame.draw.line(surf, (0, 0, 0), left_front, right_front)
        pygame.draw.line(surf, (0, 0, 0), left_front, left_back)
        pygame.draw.line(surf, (0, 0, 0), right_front, right_back)
        pygame.draw.line(surf, (0, 0, 0), left_back, right_back)

    def newSonarDistance(self, new_distance):

        if new_distance > 0 and new_distance != 4294967295:
            if len(self.sonar_distance_array) > 10:
                self.sonar_distance_array.pop(0)
            self.sonar_distance_array.append(new_distance)
            self.sonar_distance = sum(self.sonar_distance_array)/len(self.sonar_distance_array)


