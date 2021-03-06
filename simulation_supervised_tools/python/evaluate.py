#!/usr/bin/env python
import rospy
# OpenCV2 for saving an image
from cv_bridge import CvBridge, CvBridgeError

import cv2

from geometry_msgs.msg import Twist
from sensor_msgs.msg import Image
from sensor_msgs.msg import LaserScan
from std_msgs.msg import Empty
from nav_msgs.msg import Odometry

import time
import sys, select, tty, os, os.path
import numpy as np
import commands

from subprocess import call

# Check groundtruth for height
# Log position
# Check depth images for bump 
# Check time for success
# write log when finished and shutdown

# Instantiate CvBridge
bridge = CvBridge()

turtle=False # boolean indicating we are working with a trutlebot 


flight_duration = -1 #amount of seconds drone should be flying, in case of no checking: use -1
starting_height = -1 
delay_evaluation = 3
success=False
shuttingdown=False
go=False
ready=False
finished=True
min_allowed_distance=0.5 #0.8
start_time = -1
log_file ='/tmp/log'
named_log_file =log_file+'_named'
position_log_file = log_file+'_positions.txt'
pidfile="/tmp/.pid"
finished_pub=None
current_pos=[0,0,0]
starting_height = -1
eva_dis=-1
world_name='unk'
positions = []

def shutdown():
  global log_file, named_log_file, position_log_file
  finished_pub.publish(Empty())
  # import pdb; pdb.set_trace() #print("publish finised")
  try: 
    f=open(log_file, 'a')
    message = '{0} \n'.format('success' if success else 'bump')
    # message = 'success \n'
    f.write(message)
    f.close()
  except :
    print('[evaluate]: FAILED TO WRITE LOGFILE: log_file')
  try: 
    f=open(named_log_file, 'a')
    message = '{0} {1} \n'.format('success' if success else 'bump', world_name)
    f.write(message)
    f.close()
  except :
    print('[evaluate]: FAILED TO WRITE LOGFILE: named_log_file')
  else:
    time.sleep(1)
  try: 
    f=open(position_log_file, 'a')
    for pos in positions:
      f.write('{0} {1} {2}\n'.format(pos[0],pos[1],pos[2]))
    f.close()
  except :
    print('[evaluate]: FAILED TO WRITE LOGFILE: position_log_file')
  else:
    time.sleep(1)
  
  #kill process
  if os.path.isfile(pidfile):
    with open(pidfile, 'r') as pf:
      pid=pf.read()[:-1]
    # gzpid = commands.getstatusoutput('ps -ef | grep gzserver | tail -1')[1].split(' ')[]
    # print("gzserver pid: {}".format(gzpid))
    # call("$(kill -9 "+gzpid+")", shell=True)
    # time.sleep(5)
    time.sleep(1)
    call("$(kill -9 "+pid+")", shell=True)
  
  # Call drive-me-back to free space and wait for a free road sign
  if turtle:
    print("[evaluate]: Calling drive-me-back service")
    drive_back_pub.publish(Empty()) 
        
def free_road_callback(msg):
  print('[evaluate]: road is free.')
  # wait for new tf log to indicate learning is ready
  # ...
  # ready for the next round!
  ready_pub.publish(Empty())    
  shuttingdown=False
  ready=True
  finished=False

def time_check():
  global start_time, shuttingdown, success
  if start_time == -1: start_time = rospy.get_time()
  if (int(rospy.get_time()-start_time)) > (flight_duration+delay_evaluation) and not shuttingdown:
    print('[evaluate.py]: current time {0} > flight_duration {1}----------success!'.format(int(rospy.get_time()-start_time),(flight_duration+delay_evaluation)))
    success=True
    shuttingdown=True
    shutdown()
    
def depth_callback(msg):
  global shuttingdown, success
  if shuttingdown: return
  if flight_duration != -1: time_check()
  try:
    de=bridge.imgmsg_to_cv2(msg)
    # print("depth min: {0}, max: {1}, min allowed: {2}".format(np.nanmin(de[de!=0]),np.nanmax(de), min_allowed_distance))
    min_distance = np.nanmin(de)
  except CvBridgeError, e:
    print(e)
  else:
    if min_distance < min_allowed_distance and not shuttingdown and ready:
      print('[evaluate.py]: {0}: bump @ {1}'.format(rospy.get_time(), time.time()))
      success=False
      shuttingdown=True
      shutdown()

def scan_callback(data):
  global shuttingdown, ready
  if shuttingdown: return
  if flight_duration != -1: time_check()

  # Preprocess depth:
  ranges=[0.5 if r > 0.5 or r==0 else r for r in data.ranges]
  # clip left 45degree range from 0:45 reversed with right 45degree range from the last 45:
  ranges=list(reversed(ranges[:45]))+list(reversed(ranges[-45:]))

  min_distance = min(ranges)
  # print('[evaluate]: min dis: {0} min allowed: {1}'.format(min_distance,min_allowed_distance))
  if min_distance < min_allowed_distance and not shuttingdown and ready:
    print('[evaluate.py]: {0}: bump @ {1}'.format(rospy.get_time(), time.time()))
    success=False
    shuttingdown=True
    shutdown()

def gt_callback(data):
  global current_pos, ready, success, shuttingdown, positions, start_time
  current_pos=[data.pose.pose.position.x,
                  data.pose.pose.position.y,
                  data.pose.pose.position.z]
  if start_time==-1: start_time = rospy.get_time()
  positions.append(current_pos)
  if (starting_height==-1 or current_pos[2] >= starting_height) and not ready and (not turtle or go) and (rospy.get_time()-start_time)>delay_evaluation:
    print('[evaluate.py]: {0} = {1} - {2}: ready!'.format(rospy.get_time()-start_time, rospy.get_time(), start_time))
    ready_pub.publish(Empty())
    ready = True
  # print 'dis: ',(current_pos[0]**2+current_pos[1]**2)
  # if (current_pos[0] > 52 or current_pos[1] > 30) and not shuttingdown:  
  if eva_dis!=-1 and (current_pos[0]**2+current_pos[1]**2) > eva_dis and not shuttingdown:
    print '[evaluate]: dis > evadis-----------success!'
    success = True
    shuttingdown = True
    shutdown()

def go_callback(msg):
  global go
  if not go:
    go=True
    print('[evaluate] go.')

if __name__=="__main__":
  rospy.init_node('evaluate', anonymous=True)
  ## create necessary directories
  if rospy.has_param('delay_evaluation'):
    delay_evaluation=rospy.get_param('delay_evaluation')
  if rospy.has_param('flight_duration'):
    flight_duration=rospy.get_param('flight_duration')
  if rospy.has_param('min_allowed_distance'):
    min_allowed_distance=rospy.get_param('min_allowed_distance')
  if rospy.has_param('starting_height'):
    starting_height=rospy.get_param('starting_height')
  if rospy.has_param('eva_dis'):
    eva_dis=rospy.get_param('eva_dis')
  if rospy.has_param('log_folder'):
    log_folder=rospy.get_param('log_folder')
  else:
    log_folder = '/tmp/log'
  if rospy.has_param('pidfile'):
    pidfile=rospy.get_param('pidfile')
    pidfile=log_folder+'/'+pidfile
  log_file=log_folder+'/log'
  named_log_file =log_file+'_named'
  position_log_file = log_file+'_positions.txt'
  if rospy.has_param('world_name') :
    world_name = os.path.basename(rospy.get_param('world_name').split('.')[0])
    if 'sandbox' in world_name: world_name='sandbox'
  if rospy.has_param('depth_image'):
    if rospy.get_param('depth_image')!= '/scan':
      rospy.Subscriber(rospy.get_param('depth_image'), Image, depth_callback)
    else:
      print("[evaluate.py]: turtle robot")
      turtle=True
      # should listen to turtlebot scan instead...
      rospy.Subscriber(rospy.get_param('depth_image'), LaserScan, scan_callback)
      rospy.Subscriber(rospy.get_param('go'),Empty, go_callback)
  
  if rospy.has_param('ready'): 
    ready_pub = rospy.Publisher(rospy.get_param('ready'), Empty, queue_size=10)

  if turtle:
    drive_back_pub = rospy.Publisher('/drive_back', Empty, queue_size=1)
    rospy.Subscriber('/free_road', Empty, free_road_callback)
    
  if rospy.has_param('finished'): 
    finished_pub = rospy.Publisher(rospy.get_param('finished'), Empty, queue_size=10)
  
  if rospy.has_param('gt_info'): 
    rospy.Subscriber(rospy.get_param('gt_info'), Odometry, gt_callback)
  
  # spin() simply keeps python from exiting until this node is stopped	
  rospy.spin()
