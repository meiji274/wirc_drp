# wirc_drp - The WIRC+Pol Data Reduction Pipeline

**This software is work in progress and major changes may happen to the code and we provide no guarantee 
that newer version will have backward compatibility.**

**Please contact authors if you plan to use it.** 

**Start with the Tutorial Jupyter notebook in wirc_drp/Tutorial to familiarize yourself with the DRP functionalities.** 

**This is the object oriented data reduction pipeline for the WIRC+Pol instrument at Palomar Observatory.**

## Installation

1) Download or clone the repository and then run:
> python setup.py develop

2) Set a new environment variable called WIRC_DRP to the base directory of the DRP. 

3) Install all the dependencies below. 

## Dependencies

The WIRC_DRP relies on several outside packages:
- The image registration package from:
<https://github.com/keflavich/image_registration>
many thanks to the authors.
- The photuilts package: 
https://photutils.readthedocs.io/en/stable/install.html
(please check their citation request: https://photutils.readthedocs.io/en/stable/index.html)

- The OpenCV package. You can probably install it like this: ```pip install opencv-python```. (This should be installed when you run setup.py)

- The scikit-image package: http://scikit-image.org/docs/dev/install.html (This should be installed when you run setup.py)

- We use the git-python package to keep track of what version of the pipeline is being used to reduce a given file: http://gitpython.readthedocs.io/en/stable/intro.html
