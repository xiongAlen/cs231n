import tensorflow as tf
import numpy as np
import random

from tensorflow.examples.tutorials.mnist import input_data
mnist = input_data.read_data_sets("MNIST_data/", one_hot=True)

import matplotlib.pyplot as plt

sess = tf.InteractiveSession()

x = tf.placeholder(tf.float32, shape=[1, 784])
#y_ = tf.placeholder(tf.float32, shape=[1, 10])

def weight_variable(shape):
  initial = tf.truncated_normal(shape, stddev=0.1)
  return tf.Variable(initial)

def bias_variable(shape):
  initial = tf.constant(0.1, shape=shape)
  return tf.Variable(initial)

def conv2d(x, W):
  return tf.nn.conv2d(x, W, strides=[1, 1, 1, 1], padding='SAME')

def max_pool_2x2(x):
  return tf.nn.max_pool(x, ksize=[1, 2, 2, 1],
                        strides=[1, 2, 2, 1], padding='SAME')

x_image = tf.reshape(x, [-1,28,28,1])

W_conv1 = weight_variable([5, 5, 1, 32])
b_conv1 = bias_variable([32])

h_conv1 = tf.nn.relu(conv2d(x_image, W_conv1) + b_conv1)
h_pool1 = max_pool_2x2(h_conv1)

W_conv2 = weight_variable([5, 5, 32, 64])
b_conv2 = bias_variable([64])

h_conv2 = tf.nn.relu(conv2d(h_pool1, W_conv2) + b_conv2)
h_pool2 = max_pool_2x2(h_conv2)

W_fc1 = weight_variable([7 * 7 * 64, 1024])
b_fc1 = bias_variable([1024])

h_pool2_flat = tf.reshape(h_pool2, [-1, 7*7*64])
h_fc1 = tf.nn.relu(tf.matmul(h_pool2_flat, W_fc1) + b_fc1)

print(h_pool2.get_shape())

shape = h_pool2.get_shape()[1:]
print(shape)

array = np.zeros(shape)
total_size = np.prod(shape)
print(total_size)
loc = np.random.randint(0,total_size)

print("loc = ", loc)
print(np.unravel_index(loc, array.shape))
# array.ravel()[loc] = 1
array[3,3,:] = 1
array = array[np.newaxis,:,:,:]

x_input = np.zeros(x_image.get_shape())

grad_h_pool2 = tf.placeholder(tf.float32, shape=h_pool2.get_shape())
grad_x_image = tf.gradients(h_pool2, [x_image], grad_h_pool2)

init_op = tf.initialize_all_variables()
sess.run(tf.initialize_all_variables())

grad_x_image_result = sess.run(grad_x_image, feed_dict={grad_h_pool2: array, x_image: x_input})
#print(grad_x_image_result)

array_grad = grad_x_image_result[0][0,:,:,0]
non_zero_idx = np.nonzero(array_grad)

d = array_grad[non_zero_idx]
print(d.shape)
print(non_zero_idx)

print(array_grad.shape)

plt.figure(figsize=(10,10))
plt.imshow(array_grad, cmap="gray")
plt.show()
#receptive field size
