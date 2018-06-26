#!/usr/bin/env python
import rospy
# OpenCV2 for saving an image
from cv_bridge import CvBridge, CvBridgeError
import cv2
from geometry_msgs.msg import Twist
from sensor_msgs.msg import LaserScan
from std_msgs.msg import Empty
import time
import sys, select, tty, os, os.path
import numpy as np

from rospy.numpy_msg import numpy_msg
from rospy_tutorials.msg import Floats

import matplotlib.pyplot as plt
import matplotlib.animation as animation

#--------------------------------------------------------------------------------------------------------------
#
# Show scan prediction displays the predicted and the ground truth scan information.
# This node will only display if 2 sources (scan, predicted scan) is published.
# The node will save the images if save_images param is set true and there is a non-zero data_location.
#
#--------------------------------------------------------------------------------------------------------------

# Instantiate CvBridge
bridge = CvBridge()

# Initialize data saving parameters
count=0
data_location='/tmp'
save_images=False

# Scan settings
field_of_view = 104 # FOV in degrees
clip_distance = 4 # don't care about everything further than 5m away.
smooth_x = 4 # smooth over 4 neighboring bins

# Global fields
target_scan = None
predicted_scan = None

# Initialize plotting figure
fig=plt.figure(figsize=(15,5))
plt.title('Scan Predictions')

target_barcollection=plt.bar(np.arange(-field_of_view/2, field_of_view/2, 0.5*smooth_x),[clip_distance if k%2==1 else 0 for k in range(int(field_of_view/(0.5*smooth_x))) ],align='center',color='blue',width=0.4)
predicted_barcollection=plt.bar(np.arange(-field_of_view/2, field_of_view/2, 0.5*smooth_x),[clip_distance if k%2==0 else 0 for k in range(int(field_of_view/(0.5*smooth_x))) ],align='center',color='red',width=0.4)

# target_barcollection=plt.bar(np.arange(-field_of_view/2, field_of_view/2, smooth_x*0.5),[clip_distance for k in range(int(2*field_of_view/smooth_x))],align='center',color='blue',width=smooth_x*0.5/2)
# perdicted_barcollection=plt.bar(np.arange(-field_of_view/2+1, field_of_view/2+1, smooth_x*0.5),[clip_distance for k in range(int(2*field_of_view/smooth_x))],align='center',color='red',width=smooth_x*0.5/2)

def animate(n):
  # only animate if all fields are filled.
  if target_scan:
    # put even slots with target scan
    for i, b in enumerate(target_barcollection):
      if i%2==1:
        b.set_height(min(target_scan[int(i/2)], clip_distance))
      else:
        b.set_height=0
    # put odd slots with predicted scan
  if predicted_scan:
    for i, b in enumerate(predicted_barcollection):
      if i%2==0:
        b.set_height(min(predicted_scan[int(i/2)], clip_distance))
      else:
        b.set_height=0


def target_callback(data):
  """ Preprocess target scan (180degrees):
  - clip values at clip_distance
  - clip at -field_of_view/2:field_of_view
  - set zeros to nans
  - smooth over smooth_x neighboring range values
  return clean scan
  """
  global target_scan
  # clip left field_of_view/2 degree range from 0:field_of_view/2  reversed with right field_of_view/2 degree range from the last field_of_view/2 :
  data.ranges=list(reversed(data.ranges[:field_of_view/2]))+list(reversed(data.ranges[-field_of_view/2:]))
  # clip at clip_distance m and make 'broken' 0 readings also clip_distance 
  ranges=[min(r,clip_distance) if r!=0 else np.nan for r in data.ranges]
  # smooth over smooth_x bins and save in target ranges
  target_scan = [np.nanmean(ranges[i*smooth_x:i*smooth_x+smooth_x]) for i in range(int(len(ranges)/smooth_x))]
    
def predicted_callback(data):
  global predicted_scan
  predicted_scan=list(data.data[:])
  return
#   # if not ready: return
#   img = data.data
#   # check if the predicted depth contains probabilities instead:
#   if len(img.flatten()) < 10 and sum(img.flatten()) != 0: #in case only or less than 10 values are send these are most likely to be continuous output values.
#     for i in range(len(img.flatten())):
#       predicted_depth[i,:,:] = img.flatten()[i]*1/max(img.flatten())
#   else:
#     try:
#       img = img.reshape(-1,55,74)
#     except:
#       return
#       # img = predicted_depth.reshape(55,74)
#     img = img*1/5.
#     n=3
#     img = np.kron(img, np.ones((n,n)))
#     predicted_depth = img[:,:,:]
#   # update()


def cleanup():
  """Get rid of the animation on shutdown"""
  plt.close(fig)
  plt.close()

  
if __name__=="__main__":
  rospy.init_node('show_scan', anonymous=True)
  
  rospy.Subscriber('/depth_prediction', numpy_msg(Floats), predicted_callback, queue_size = 1)

  if rospy.has_param('depth_image') and 'scan' in rospy.get_param('depth_image'):
    rospy.Subscriber(rospy.get_param('depth_image'), LaserScan, target_callback, queue_size = 1)
  
  # if rospy.has_param('saving_location'):
  #   loc=rospy.get_param('saving_location')
  #   if loc[0]=='/':
  #     saving_location=loc
  #   else:
  #     saving_location='$HOME/pilot_data/flights/'+loc
  # print(saving_location)
  # if rospy.has_param('save_images'):
  #   save_images=rospy.get_param('save_images')
  # if False:
  # # if save_images:
  #   print '----------------save images to: ',saving_location
  #   recording = True
  #   if not os.path.isdir(saving_location):
  #     try:
  #       os.mkdir(saving_location)
  #     except:
  #       pass 
    
  if rospy.has_param('graphics'):
    if rospy.get_param('graphics'):
      print("[show_scan_prediction]: showing graphics.")
      anim=animation.FuncAnimation(fig,animate)
      plt.show()
  rospy.on_shutdown(cleanup)

  rospy.spin()
