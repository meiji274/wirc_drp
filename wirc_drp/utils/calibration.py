# -*- coding: utf-8 -*-
"""
Created on Fri Feb 17 00:53:59 2017

@author: kaew
Basic Reduction Routines

Perform dark subtraction and flat field correction
"""
import astropy.io.fits as f
import numpy as np
import matplotlib.pyplot as plt
from astropy.stats import sigma_clip
from scipy.stats import mode
from scipy.ndimage import median_filter, shift, rotate
import os
import warnings
from image_registration import chi2_shift
#from wircpol.DRP.reduction.constants import *
from wirc_drp.constants import *
#from pyklip import klip
from wirc_drp.masks.wircpol_masks import * ### Make sure that the wircpol/DRP/mask_design directory is in your Python Path!
from wirc_drp import version # For versioning (requires gitpython 'pip install gitpython')

def masterFlat(flat_list, master_dark_fname, normalize = 'median', sig_bad_pix = 3,  hotp_map_fname = None):
    
    """
    Create a master normalized flat file given a list of fits files of flat fields from
    WIRC.
    
    flats are scaled with mode or median (in case that illumination change, like in twilight flat)
    and then median combined to reject spurious pixels. 

    It also saves a bad pixel map of pixels that are further than sig_bad_pix sigma away from the median (mean?)
    
    
    flat_list: a list of file names for flat fields
    master_dark_fname: a file name of a combined dark frame of the same exposure time as these flats
    normalize: How to normalize the flat field, by 'median' or 'mode'
    sig_bad_pix: we define bad pixels as pixels with value more than sig_bad_pix*sqrt(variance) away from the median of the frame
    hotp_map_fname: file name of the hot pixel map from the dark frame.
    """

    #Open the master dark
    master_dark_hdu = f.open(master_dark_fname)
    master_dark = master_dark_hdu[0].data
    dark_shape = np.shape(master_dark)
    print(("Subtracting {} from each flat file".format(master_dark_fname)))
    dark_exp_time = master_dark_hdu[0].header['EXPTIME']

    #Open all files into a 3D array
    foo = np.empty((dark_shape[0],dark_shape[1],len(flat_list)))

    #Open first flat file to check exposure time
    first_flat_hdu = f.open(flat_list[0])
    flat_exp_time = first_flat_hdu[0].header['EXPTIME']
    #We've already read it, so we'll stick it in foo
    foo[:,:,0] = first_flat_hdu[0].data
    
    if dark_exp_time != flat_exp_time:
        print("The master dark file doesn't have the same exposure time as the flats. We'll scale the dark for now, but this isn't ideal", UserWarning)
        factor = flat_exp_time/dark_exp_time
    else: 
        factor = 1. 
    
    print("Combining flat files")
    for i in range(1,len(flat_list)):
        #subtract dark for each file, then normalize by mode
        hdu = f.open(flat_list[i])
        d_sub = hdu[0].data  - factor*master_dark
        #normalize
        if normalize == 'mode':
            d_sub = d_sub/mode(d_sub, axis = None, nan_policy = 'omit')
        elif normalize == 'median':
            d_sub = d_sub/np.nanmedian(d_sub)
        foo[:,:,i] = d_sub
        
    #Median combine frames
    flat = np.median(foo, axis = 2)
        
    #Filter bad pixels
    bad_px = sigma_clip(flat, sigma = sig_bad_pix)
    
    #Normalize good pixel values
    if normalize == 'median':
        norm_flat = flat/np.nanmedian(bad_px.data[~bad_px.mask])
    elif normalize == 'mode':
        norm_flat = flat/mode(flat, axis = None, nan_policy = 'omit')
    #Stick it back in the last hdu 
    hdu[0].data = norm_flat

    #Add pipeline version and history keywords
    vers = version.get_version()
    hdu[0].header.set('PL_VERS',vers,'Version of pipeline used for processing')
    hdu[0].header['HISTORY'] = "############################"
    hdu[0].header['HISTORY'] = "Created master flat by median combining the following:"
    for i in range(len(flat_list)):
        hdu[0].header['HISTORY'] = flat_list[i]
    hdu[0].header['HISTORY'] = "Normalized to the median of the master flat"
    hdu[0].header['HISTORY'] = "Performed bad pixel sigma klipping with cutoff of {}sigma".format(sig_bad_pix)
    hdu[0].header['HISTORY'] = "############################"

    #Parse the last fileanme
    flat_outname = flat_list[-1].rsplit('.',1)[0]+"_master_flat.fits"
    print(("Writing master flat to {}".format(flat_outname)))
    #Write the fits file
    hdu.writeto(flat_outname, overwrite=True)

    #If there's already a hot pixel map then we'll add to it. 
    if hotp_map_fname != None:
        #read in the existing bp map
        hdu = f.open(hotp_map_fname)
        hdu[0].data += np.array(bad_px.mask, dtype=float)
        bp_outname = flat_list[-1].rsplit('.',1)[0]+"_bp_map.fits"

    else: 
        ##### Now write the bad pixel map
        hdu[0].data = np.array(bad_px.mask, dtype=float)
        #Parse the last fileanme
        bp_outname = flat_list[-1].rsplit('.',1)[0]+"_bp_map.fits"
    
    #Add history keywords
    hdu[0].header['HISTORY'] = "############################"
    hdu[0].header['HISTORY'] = "Created badpixel map by sigma klipping {}".format(flat_outname)
    hdu[0].header['HISTORY'] = "Bad pixel cutoff of {}sigma".format(sig_bad_pix)
    hdu[0].header['HISTORY'] = "A pixel value of 1 indicates a bad pixel"
    hdu[0].header['HISTORY'] = "############################"

    print(("Writing bad pixel map to {}".format(bp_outname)))
    #Write the fits file
    hdu.writeto(bp_outname, overwrite=True)

    return flat_outname, bp_outname
    
def masterDark(dark_list, sig_hot_pix = 5):

    """
    Create a master dark file from the median of a list of fits files
    It also saves a bad pixel map of hot pixels and pixels that have a value of 0. in the dark.

    """
    #Open all files into a 3D array
    print("Creating a master dark")
    foo = np.empty((2048,2048,len(dark_list)))
    for i in range(len(dark_list)):
        hdu = f.open(dark_list[i])
        foo[:,:,i] = hdu[0].data  
    
    #Create the master dark
    master_dark = np.median(foo, axis = 2)

    hot_px = sigma_clip(master_dark, sigma = sig_hot_pix)

    zero_px = master_dark == 0. 

    bad_px = hot_px.mask | zero_px

    #Stick it back in the last hdu 
    hdu[0].data = master_dark

    #Add pipeline version and history keywords
    vers = version.get_version()
    hdu[0].header.set('PL_VERS',vers,'Version of pipeline used for processing')
    hdu[0].header['HISTORY'] = "############################"
    hdu[0].header['HISTORY'] = "Created master dark by median combining the following frames"
    for i in range(len(dark_list)):
        hdu[0].header['HISTORY'] = dark_list[i]
    hdu[0].header['HISTORY'] = "############################"

    #Parse the last fileanme
    dark_outname = dark_list[-1].rsplit('.',1)[0]+"_master_dark.fits"
    print(("Writing master dark to {}".format(dark_outname)))
    #Write the fits file
    hdu.writeto(dark_outname, overwrite=True)

    #Stick it back in the last hdu 
    hdu[0].data = np.array(bad_px, dtype=float)*2

    #Add history keywords
    #Add history keywords
    hdu[0].header['HISTORY'] = "############################"
    hdu[0].header['HISTORY'] = "Created hot pixel map by sigma clipping {}".format(dark_outname)
    hdu[0].header['HISTORY'] = "Bad pixel cutoff of {}sigma".format(sig_hot_pix)
    hdu[0].header['HISTORY'] = "A pixel value of 2 indicates a hot pixel"
    hdu[0].header['HISTORY'] = "############################"

    #Parse the last fileanme
    bp_outname = dark_list[-1].rsplit('.',1)[0]+"_bp_map.fits"
    print(("Writing master dark to {}".format(bp_outname)))
    #Write the fits file
    hdu.writeto(bp_outname, overwrite=True)

    return dark_outname, bp_outname
    
def interpBadPix(science, bad_px):
    """
    Interpolate over bad pixels on the science image
    To preserve spectral information, interpolate orthogonally to the trace in 
    each quadrant
    """

def calibrate(science_list_fname, master_flat_fname, master_dark_fname, bp_map_fname, mask_bad_pixels = False, clean_Bad_Pix=True, replace_nans=False, background_fname = None ):
    """
    Subtract dark; divide flat
    Bad pixels are masked out using the bad_pixel_map with 0 = bad and 1 = good pixels

    """

    #Get the list of science frames
    #science_list = np.loadtxt(science_list_fname, dtype=str)
    science_list = science_list_fname

    #Open the master dark
    master_dark_hdu = f.open(master_dark_fname)
    master_dark = master_dark_hdu[0].data
    dark_shape = np.shape(master_dark)
    print(("Subtracting {} from each flat file".format(master_dark_fname)))
    dark_exp_time = master_dark_hdu[0].header['EXPTIME']

    #Open the master flat
    master_flat_hdu = f.open(master_flat_fname)
    master_flat = master_flat_hdu[0].data
    print(("Dividing each file by {}".format(master_flat_fname)))
    dark_exp_time = master_dark_hdu[0].header['EXPTIME']

    #Open the master flat
    bp_map_hdu = f.open(bp_map_fname)
    bad_pixel_map = bp_map_hdu[0].data
    bad_pixel_map_bool = np.array(bad_pixel_map, dtype=bool)
    print(("Using bad pixel map {}".format(bp_map_fname)))

    if background_fname != None:
        background_hdu = f.open(background_fname)
        background = background_hdu[0].data
        print("Subtracting background frame {} from all science files".format(background_fname))


    for fname in science_list:
        #Open the file
        print(("Calibrating {}".format(fname
            )))
        hdu = f.open(fname)
        data = hdu[0].data
        science_exp_time = hdu[0].header['EXPTIME']

        if dark_exp_time != science_exp_time:
            warnings.warn("The master dark file doesn't have the same exposure time as the flats. We'll scale the dark for now, but this isn't ideal", UserWarning)
            factor = science_exp_time/dark_exp_time
        else: 
            factor = 1. 

        #Subtract the dark, divide by flat
        redux = ((data - factor*master_dark)/master_flat)
        #get rid of crazy values at bad pixel
        redux = redux*~bad_pixel_map_bool

        if background_fname != None:
            redux -= background

        if clean_Bad_Pix:
            # plt.plot(bad_pixel_map_bool)
            redux = cleanBadPix(redux, bad_pixel_map_bool)
            #redux = ccdproc.cosmicray_lacosmic(redux, sigclip=5)[0]

            # redux = ccdproc.cosmicray_median(redux, mbox=7, rbox=5, gbox=7)[0]

        #Mask the bad pixels if the flag is set
        if mask_bad_pixels:
            redux *= ~bad_pixel_map_bool

        if replace_nans: 
            # nan_map = ~np.isfinite(redux)
            # redux = cleanBadPix(redux, nan_map)
            # plt.imshow(redux-after)
            nanmask = np.isnan(redux) #nan = True, just in case this is useful
            redux = np.nan_to_num(redux)

        #Put the cablibrated data back in the HDU list
        hdu[0].data = redux

        #Add pipeline version and history keywords
        vers = version.get_version()
        hdu[0].header.set('PL_VERS',vers,'Version of pipeline used for processing')
        hdu[0].header['HISTORY'] = "Subtracting {} from each flat file".format(master_dark_fname)
        hdu[0].header['HISTORY'] = "Dividing each file by {}".format(master_flat_fname)

        if background_fname != None:
            hdu[0].header['HISTORY'] = "Subtracted background frame {}".format(background_fname)
        
        if mask_bad_pixels:
            hdu[0].header['HISTORY'] = "Masking all bad pixels found in {}".format(bp_map_fname)

        if clean_Bad_Pix:
            hdu[0].header['HISTORY'] = "Cleaned all bad pixels found in {} using a median filter".format(bp_map_fname)

        # #Append the bad pixel list to the HDU list
        # hdu.append(f.PrimaryHDU([bad_pixel_map]))
        # hdu[1].header['HISTORY'] = "Appending bad pixel map :{}".format(bp_map_fname)
        # hdu[1].header['HISTORY'] = "0 = good pixel"
        # hdu[1].header['HISTORY'] = "1 = bad pixel from flat fields"
        # hdu[1].header['HISTORY'] = "2 = hot pixel from darks"
        

        outname = fname.split('.')[0]+"_calib.fits"
        print(("Writing calibrated file to {}".format(outname)))
        #Save the calibrated file
        hdu.writeto(outname, overwrite=True)

        # f.PrimaryHDU(redux).writeto('redux_'+i, overwrite = True)
        
def cleanBadPix(redux_science, bad_pixel_map, median_box = 5):
    """
    rudimentary version of interpBadPix, use median filter
    """
    #add negative pixels to the bad pixel map
    bad_pixel_map = np.logical_or(bad_pixel_map, redux_science <= 0)
    # im = np.copy(redux_science)
    # im[np.where(bad_pixel_map)[1]] = 0.
    med_fil = median_filter(redux_science, size = median_box)

    cleaned = redux_science*~bad_pixel_map + med_fil*bad_pixel_map  
    # print('so clean')

    return cleaned

def sum_images(filelist):
    """
    Super simple sum of all the images in a list. 
    """
    
    nfiles = np.size(filelist)

    print("Summing together {} files".format(nfiles))

    ims = []

    for fname in filelist: 
        hdu = f.open(fname)
        ims.append(hdu[0].data)

    ims = np.array(ims)

    sum_im = np.nansum(ims, axis=0)
    hdu[0].data = sum_im

    #Add pipeline version and history keywords
    vers = version.get_version()
    hdu[0].header.set('PL_VERS',vers,'Version of pipeline used for processing')
    hdu[0].header['HISTORY'] = "Summed up the following images:"
    
    for fname in filelist:
        hdu[0].header['HISTORY'] = fname

    hdu[0].header['HISTORY'] = "######################"

    outname = filelist[-1].split('.')[0]+'_summed.fits'

    print("Writing out final file to {}".format(outname))

    hdu.writeto(outname, overwrite=True)

def get_relative_image_offsets(cutouts, plot = False, save_cutout = False):

    '''
    This function returns the relative x and y offsets between a set of images, 
    determined through cross correlation (using the chi2_shift image_registration python packge)
    It really works best on either very bright sources or on sources that have been background subracted. 

    Inputs: 
        cutouts         -   an array of cutouts with dimensions [m,n,k,l,l] where m is the number of images, 
                            n is the number of sources per image, k is the number of traces (probably always 4), 
                            and l is the height and width of the cutout (usually 80 for J and bigger for H-band)

    Outputs: 
        offsets -   an [m-1, n, 4] sized array, where the components of the third dimension are [x,y, xerr, yerr]
                    Note: xerr and yerr aren't currently working very well. 
    '''

    #Get cutouts info
    sz = np.shape(cutouts)
    nfiles = sz[0]
    n_sources = sz[1]
    cutout_sz = sz[3]

    #The output 
    offsets = []

    #Stack the first image horizontally: 
    im0_stacks = []
    for j in range(n_sources):
        #Create the horizontal stack
        stack = np.concatenate((cutouts[0,j,0,:,:], cutouts[0,j,1,:,:], cutouts[0,j,2,:,:],cutouts[0,j,3,:,:]), axis=1)
        
        #Get rid of outlying pixels
        tmp = np.copy(stack)*0.
        stack = median_filter(stack, size=5, output=tmp) 
        stack = tmp
        im0_stacks.append(stack)

    #Make the list a numpy array
    im0_stacks = np.array(im0_stacks)
    #plt.imshow(im0_stacks[0], origin = 'lower')
    #plt.show()

    #Step through the remaining files and calculate their relative offset compared to the first file. 
    for i in np.arange(0,nfiles): #include the first frame as a sanity check
        img_offset = []
        for j in range(n_sources):
            #Stack this cutout
            horiz_stack = np.concatenate((cutouts[i,j,0,:,:], cutouts[i,j,1,:,:], cutouts[i,j,2,:,:],cutouts[i,j,3,:,:]), axis=1)
            
            #To get rid of bad pixels
            tmp = np.copy(horiz_stack)*0.
            horiz_stack = median_filter(horiz_stack, size=5, output=tmp) #To get rid of mixed 
            horiz_stack = tmp
            
            #Calculate the image offsets
            #plt.imshow(horiz_stack, origin = 'lower')
            #plt.show()
            shifted = chi2_shift(im0_stacks[j,:,:],horiz_stack, zeromean=True, verbose=False, return_error=True)
            img_offset.append(shifted)

        offsets.append(img_offset)
        if plot:
            plt.figure(figsize = (12,3))
            plt.imshow(np.array(im0_stacks[0]) - shift(horiz_stack,[-img_offset[0][1]+0.5,-img_offset[0][0]], order = 4 ), origin = 'lower')
            plt.show()
        if save_cutout:
            f.PrimaryHDU(shift(horiz_stack,[-img_offset[0][1]+0.5,-img_offset[0][0]], order = 4 )).writeto(str(i)+'.fits',overwrite = True)
            f.PrimaryHDU(np.array(im0_stacks[0]) - shift(horiz_stack,[-img_offset[0][1]+0.5,-img_offset[0][0]], order = 4 )).writeto(str(i)+'_sub.fits', overwrite = True)
        #for debugging
        #print( img_offset[0][1]-0.5, img_offset[0][0]  )
    return offsets

def register_and_combine_raw(direct_image_fname, spec_list_fname, datadir = "", background_img_fname = None, locations= None, cutouts = None, quiet=True, 
                            combine = 'median', save_fits=True, save_each = False, plot=False):
    #
    # This functions reads in a list of science frames, performs cross correlation and then shifts and combines them
    #
    # Inputs
    #    direct_image_fname      -   a string that holds the path and filename to the direct image, which is used to find the locations
    #                                of the sources in the image. If the keyword 'locations' is provided no direct image is read, 
    #                                and instead the provided locations are used
    #    spec_list_fname         -   a string that holds the path and filename of a list of science images
    #    background_img_fname    -   (keyword) a string keyword that holds the path and filename of a background image to be subtracted before cross correlation
    #    locations               -   (keyword) an array of locations of the sources in the image. If this is provided then no direct image is read. 
    #                                You might provide this if you've already read in the direct image and have already found the source locations, or if
    #                                 you want to determine them yourself
    #     cutouts                 -   (keyword) an array of cutouts with dimensopns [m,n,k,l,l] where m is the number of images, 
    #                                 n is the number of sources per image, k is the number of traces (probably always 4), 
    #                                 and l is the height and width of the cutout (usually 80 for J and bigger for H-band). 
    #                                 If you provide this keyword cutouts will not be extracted from the science images and these cutouts will be used
    #                                 to determine image offsets. However the science images will still be read and shifted. 
    #     save_fits               -   (keyword) if set to true then save the registered and combined images 
    #     save_each               -   (keyword) if true then save the aligned version of each input image. 

    # Outputs
    #     spec_image              -   the name of the output file where the combined image was saved

    #If locations == None then automatically find the source locations. 
    if locations == None:
        #The mask - required to find the locations
        mask = cross_mask_ns.astype('bool')

        #### Read in the direct image to get the source locations
        direct_image = f.open(direct_image_fname)[0].data
        locations = coarse_regis.coarse_regis(direct_image, mask, threshold_sigma = 5, guess_seeing = 4, plot = plot)  
    
    #The number of sources found
    n_sources = np.shape(locations[0,:])[0]+1

    #For the cross correlation to work reliably a background image should be supplied. 
    if background_img_fname != None:
        bkg_img = f.open(background_img_fname)[0].data
        bkg_itime = f.open(background_img_fname)[0].header["EXPTIME"]

    #Get the list of spectral images
    spec_images = a.read(spec_list_fname, format = "fast_no_header")['col1']
    n_images = np.size(spec_images)

    #An array that will hold all the images
    spec_stack = np.zeros([n_images, detector_size, detector_size])

    cutouts = []
    
    #Step through all the images, save the traces cutouts and put the full image in spec_stack
    for j,i in enumerate(spec_images):

        if not quiet:
            print("\nReading in file {}, ({} from {})".format(i,j+1,len(spec_images)))
        spectral_hdulist = f.open(datadir+i)
        spectral_image = np.nan_to_num(spectral_hdulist[0].data)
        scitime = spectral_hdulist[0].header["EXPTIME"]
        
        #TODO: ADD CHECK TO MAKE SURE FILES HAVE SAME EXPOSURE TIME. 

        #### Get the Filter Info ####
        aft_filter = spectral_hdulist[0].header['AFT']
        filter_name = aft_filter[0]
        if filter_name != 'J' and filter_name != 'H':
            print("The pipeline was expecting either a J- or H-band filter but found {} instead".format(aft_filter))
            print("Returning.\n")
            break
        else: 
            if not quiet: 
                print("Found a {}-band filter in the header of file {}".format(filter_name,i))
        #Getting info about the filter. 
        lb,dlb,f0,filter_trans_int, central_wl = getFilterInfo(filter_name)
        
        #Status update
        if not quiet: 
            print ("Cutting out the traces")
        
        #Subtract a background if present. 
        if background_img_fname != None:
            if not quiet:
                print("Subtracting {} from the cutouts as background".format(background_img_fname))
            # plt.imshow(spectral_image-bkg_img*scitime/bkg_itime, vmin=0, vmax=50)
            cutouts.append(coarse_regis.extract_traces(np.copy(spectral_image-bkg_img*scitime/bkg_itime), locations, flip = False))
        else: 
            cutouts.append(coarse_regis.extract_traces(np.copy(spectral_image), locations, flip = False))

        #Put the image in the stack
        spec_stack[j,:,:] = spectral_image

    #Make cutouts an array and get the size
    cutouts = np.array(cutouts)
    sz = cutouts.shape
    cutout_sz = sz[3]
    
    #Calculate the image offsets 
    offsets = get_relative_image_offsets(cutouts, plot = plot, save_cutout = True)
    offsets = np.array(offsets)

    #A list of all the offsets to write to the header later
    dx_list = []
    dy_list = []

    #Now shift images using pyklip.rotate -- Can think about writing out own code, or copying this code so people don't have to get pyklip to use wircpol
    #print('Offsets length = ', len(offsets))
    #print(n_images - 1)
    for i in np.arange(0,n_images):
        

        #Calculate the mean offset of sources outside the slit
        where_slitless = np.where(locations[:,1] == 'slitless')[0]
        #print(offsets[i,where_slitless])
        dx = np.mean(offsets[i,where_slitless,0])
        dy = np.mean(offsets[i,where_slitless,1])-0.5 #for some reason...

        dx_list.append(dx)
        dy_list.append(dy)

        if not quiet:
            print("Registering frame {} with (dx,dy) = ({},{})".format(i,dx,dy))

        #The old and new centers
        old_center = np.array([cutout_sz/2., cutout_sz/2.])
        new_center = old_center-[dx,dy]

        #Now re-align the images
        #print('Max value ', np.max(spec_stack[i,:,:]))
        #spec_stack[i,:,:] = klip.align_and_scale(spec_stack[i,:,:], new_center, old_center=old_center, scale_factor=1,dtype=float)
        spec_stack[i,:,:] = shift(spec_stack[i,:,:], [-dy,-dx], order = 4)
        #print('NaNs',len(spec_stack[i,:,:][np.isnan(spec_stack[i,:,:])]))
        
        #if save_each, save the aligned version of each file by adding _aligned at the end of the name before .fits
        if save_each:
            #file name
            outname = spec_images[i].rsplit('.',1)[-2]+'_aligned.fits'
            #data
            spectral_hdulist[0].data = spec_stack[i,:,:]
            #Add pipeline version and history keywords
            vers = version.get_version()
            hdu[0].header.set('PL_VERS',vers,'Version of pipeline used for processing')
            spectral_hdulist[0].header['HISTORY'] = "######"
            spectral_hdulist[0].header['HISTORY'] = "register_and_combine_raw: Found relative offsets with respect to the image: "
            spectral_hdulist[0].header['HISTORY'] = "{} (dx,dy) = ({}, {})".format(spec_images[0], dx_list[0], dy_list[0])
            spectral_hdulist[0].header['HISTORY'] = "######"
            #write
            spectral_hdulist.writeto(outname, overwrite = True)

    #Collapse the image by it's sum, median, or mean based on 'combine' parameter. Default is median. 
    if combine == 'sum':
        comb_spec = np.nansum(spec_stack, axis=0)
    elif combine == 'median':
        comb_spec = np.nanmedian(spec_stack, axis = 0)
    elif combine == 'mean':
        comb_spec = np.nanmean(spec_stack, axis = 0)
    else:
        print(combine+' is not an option. Use median instead.')
        comb_spec = np.nanmedian(spec_stack, axis = 0)


    dx_list = np.array(dx_list)
    dy_list = np.array(dy_list)

    #Save the final image to a fits file
    outname = spec_images[-1].rsplit('.',1)[-2]+'_combined.fits'
    if save_fits: 
        outname = spec_images[-1].rsplit('.',1)[-2]+'_combined.fits'
        #these are spectral_hdulist from the last file in the spec_list
        spectral_hdulist[0].data = comb_spec

        #Add pipeline version and history keywords
        vers = version.get_version()
        spectral_hdulist[0].header.set('PL_VERS',vers,'Version of pipeline used for processing')
        spectral_hdulist[0].header['HISTORY'] = "######"
        spectral_hdulist[0].header['HISTORY'] = "register_and_combine_raw: Found relative offsets, reigstered the following images: "
        spectral_hdulist[0].header['HISTORY'] = "{} (dx,dy) = ({}, {})".format(spec_images[0], dx_list[0], dy_list[0])
        
        for i in np.arange(1,n_images-1):
            spectral_hdulist[0].header['HISTORY'] = "{} (dx,dy) = ({}, {})".format(spec_images[i], dx_list[i-1], dy_list[i-1])
        spectral_hdulist[0].header['HISTORY'] = "Combine files by {}".format(combine)
        spectral_hdulist[0].header['HISTORY'] = "Total files combined: {}".format(n_images)
        spectral_hdulist[0].header['HISTORY'] = "######"

        spectral_hdulist[0].header['NFILES'] = n_images

        if not quiet:
            print("Writing fits to {}".format(datadir+outname))

        spectral_hdulist.writeto(outname, overwrite=True)

    return outname

def shiftSub(image, slit_gap1, slit_gap2):
    """
    Create a full frame background subtracted image. The background image is an average between a frame shifted
    to +x by slit_gap1 pixel, and -x by slit_gap2 pixel. This is then subtracted off of the image.
    """
    bkg = (shift(image,(0,slit_gap1), order = 3) + shift(image,(0,-slit_gap2), order = 3))/2.
    return image - bkg


    
    