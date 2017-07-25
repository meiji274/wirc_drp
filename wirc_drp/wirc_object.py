import numpy as np
from astropy.io import fits
import matplotlib.pyplot as plt
import warnings

import warnings

import wirc_drp.utils.image_utils as image_utils
import wirc_drp.utils.spec_utils as spec_utils
import wirc_drp.utils.calibration as calibration
from wirc_drp import version # For versioning (requires gitpython 'pip install gitpython')
from wirc_drp.masks import * ### Make sure that the wircpol/DRP/mask_design directory is in your Python Path!


class wirc_data(object):

    """
    A wirc data file, that may include reduced data products

    Args:
        raw_filename: The filename of the raw image [optional]
        wirc_object_filename: The filename

    Attributes:
        full_image: Array of shape (y,x) [probably 2048 x 2048]
        header: An astropy fits header corresponding to the raw data file [including history of data reduction]
        
        dark_fn: the filename for the dark file used to correct this image
        flat_fn: the filename for the flat file used to correct this image
        bkg_fn: the filename for the bkg file subtracted off this image 
        bp_fn: the filename of the bad pixel map
        
        filelist: If this file is the result of multiple files being combined, this is a string list of all the filenames of length n_files
        dxdy_list: If this file is the result of multiple files being combined, this is an array of [nfiles,dx,dy] that hold the shifts applied to each image before combining

        n_sources: the number of sources in the full_image
        source_list: A list of n_sources wircpol_source objects

    """
    def __init__(self, raw_filename=None, wirc_object_filename=None, dark_fn = None, flat_fn = None, bp_fn = None, bkg_fn = None):

        ## Load in either the raw file, or the wircpol_object file
        if raw_filename != None and wirc_object_filename != None:
            print("Can't open both a raw file and wircpol_object, ignoring the raw file and loading the wirc_object_file ")
            print("Loading a wircpol_data object from file {}".format(wirc_object_filename))
            self.load_wirc_object(wirc_object_filename)

        elif wirc_object_filename != None:
            print("Loading a wirc_data object from file {}".format(wirc_object_filename))
            self.load_wirc_object(wirc_object_filename)

        elif raw_filename != None:
            print("Creating a new wirc_data object from file {}".format(raw_filename))
            self.raw_filename = raw_filename
            
            hdu = fits.open(raw_filename)
            self.full_image = hdu[0].data
            self.header = hdu[0].header
            
            

            self.header['RAW_FN'] = raw_filename

            self.filelist = [raw_filename]
            self.dxdy_list = [[0.,0.]]

            #### Get the Filter Info ####
            aft_filter = self.header['AFT']
            filter_name = aft_filter[0]
            if filter_name != 'J' and filter_name != 'H':
                print("The pipeline was expecting either a J- or H-band filter but found {} instead".format(aft_filter))
                print("Returning.\n")
                # break
            else: 
                print("Found a {}-band filter in the header of file {}".format(filter_name,raw_filename))
            self.filter_name = filter_name

            self.calibrated = False
            self.bkg_subbed = False

            self.n_sources = 0
            self.source_list = []

            self.dark_fn = dark_fn        
            self.flat_fn = flat_fn
            self.bkg_fn = bkg_fn
            self.bp_fn = bp_fn
        else: #for a blank wirc object
            self.calibrated = False
            self.bkg_subbed = False
            self.n_sources = 0
            self.source_list = []
            

    def calibrate(self, clean_bad_pix=True, replace_nans=True, mask_bad_pixels=False):
        '''
        Apply dark and flat-field correction
        '''

        #TODO Add checks to make sure the flatnames are not none

        if not self.calibrated:

            if self.dark_fn != None:
                #Open the master dark
                master_dark_hdu = fits.open(self.dark_fn)
                master_dark = master_dark_hdu[0].data
                dark_shape = np.shape(master_dark)
                print(("Subtracting {} from the image".format(self.dark_fn)))
                dark_exp_time = master_dark_hdu[0].header['EXPTIME']

                #Checking Dark Exposure times and scaling if need be
                if dark_exp_time != self.header["EXPTIME"]:
                    print("The master dark file doesn't have the same exposure time as the flats. We'll scale the dark for now, but this isn't ideal")
                    factor = self.header["EXPTIME"]/dark_exp_time
                else: 
                    factor = 1. 

                #Subtract the dark
                self.full_image = self.full_image-factor*master_dark

                #Update the header
                self.header['HISTORY'] = "Subtracting {} from each flat file".format(self.dark_fn)
                self.header['DARK_FN'] = self.dark_fn

            else:
                print("No dark filename found, continuing without subtracting a dark")

            if self.flat_fn != None:
                #Open the master flat
                master_flat_hdu = fits.open(self.flat_fn)
                master_flat = master_flat_hdu[0].data
                print(("Dividing the image by {}".format(self.flat_fn)))

                #Divide the flat
                self.full_image = self.full_image/master_flat

                #Update the header                
                self.header['HISTORY'] = "Dividing each file by {}".format(self.flat_fn)
                self.header["FLAT_FN"] = self.flat_fn
                
            else:
                print("No flat filename found, continuing without divinding by a falt")

            #If a background image is provided then subtract it out
            if self.bkg_fn != None:
                background_hdu = fits.open(self.bkg_fn)
                background = background_hdu[0].data
                print("Subtracting background frame {} from all science files".format(self.bkg_fn))

                if self.dark_fn != None:
                    background = background - factor*master_dark

                scale_bkg = np.nanmedian(self.full_image)/np.nanmedian(background)

                #Subtract the background
                self.full_image -= scale_bkg*background

                #Update the header
                self.header['HISTORY'] = "Subtracted background frame {}".format(self.bkg_fn)
                self.header['BKG_FN'] = self.bkg_fn   

            #If a badpixel map is provided then correct for bad pixels, taking into account the clean_bad_pix and mask_mad_pixels flags
            if self.bp_fn != None:
                #Open the bad pixel map
                bp_map_hdu = fits.open(self.bp_fn)
                bad_pixel_map = bp_map_hdu[0].data
                bad_pixel_map_bool = np.array(bad_pixel_map, dtype=bool)
                print(("Using bad pixel map {}".format(self.bp_fn)))

                if clean_bad_pix:
                    redux = calibration.cleanBadPix(self.full_image, bad_pixel_map_bool)
                    self.header['HISTORY'] = "Cleaned all bad pixels found in {} using a median filter".format(self.bp_fn)
                    self.header['CLEAN_BP'] = "True"
                
                #Mask the bad pixels if the flag is set
                if mask_bad_pixels:
                    redux = self.full_image*~bad_pixel_map_bool

                    #Update the header
                    self.header['HISTORY'] = "Masking all bad pixels found in {}".format(self.bp_fn)
                    self.header['BP_FN'] = self.bp_fn

                self.full_image = redux

            else:
                print("No Bad pixel map filename found, continuing without correcting bad pixels")


            #Replace the nans if the flag is set. 
            if replace_nans: 
                nanmask = np.isnan(self.full_image) #nan = True, just in case this is useful
                self.full_image = np.nan_to_num(self.full_image)

            #Turn on the calibrated flag
            self.calibrated = True
        
        else: 
            print("Data already calibrated")


    def sub_background_image(self, scale_itime=True):
        """
        Subtr sact a background frame

        Args:
            scale_itime - If true then scale the background image to have the same integration time as the science frame. 

        """

        if self.bkg_fn != None:
            # try: 
            background_hdu = f.open(background_fname)
            background = background_hdu[0].data

            bkg_itime = f.open(background_img_fname)[0].header["EXPTIME"]
            print("Subtracting background frame {} from all science files".format(self.bkg_fn))

            if scale_itime:
                scitime = self.header["EXPTIME"]
                background = background * scitime/bkg_itime

            #Subtract a background image
            self.full_image -= background

            self.bkg_subbed = True
        else: 
            print("Background filename not set, please set wircpol_data.bkg_fn property to the filename of your background file")

    
    def save_wirc_object(self, wirc_object_filename, overwrite = True):
        #Save the object to a fits file   

        # vers = version.get_version()
        # self.header.set('PL_VERS',vers,'Version of pipeline used for processing')
        #common indexing notes for save_wirc_object and load_wirc_object:
        #----#(2*i)+1 is a conversion from the index, i, of the source in source_list to the index of the source in hdulist
        #----#(2*i)+2 is a conversion from the index, i, of the source in source_list to the index of the source's corresponding table in hdulist
        
       

        #TODO: Update the header keywords below to include a keyword description like PS_VERS above

        #These may not always be set by other function
        self.header["NSOURCES"] = self.n_sources
        self.header["DARK_FN"] = self.dark_fn
        self.header["FLAT_FN"] = self.flat_fn
        self.header["BP_FN"] = self.bp_fn
        self.header["BKG_FN"] = self.bkg_fn

        #Have the data been calibrated/background subtracted? 
        self.header["CALBRTED"] = self.calibrated
        self.header["BKG_SUBD"] = self.bkg_subbed

        hdu = fits.PrimaryHDU(self.full_image)
        hdu.header = self.header

        hdulist = fits.HDUList([hdu])

        #Now for each source, create a ImageHDU, this works even if the cutouts haven't been extracted
        #Now for each source, create a TableHDU
        for i in range(self.n_sources):
            #print ('Starting Iteration #',i);
            
            #Create an ImageHDU for each of the sources
            # source_hdu = fits.ImageHDU(self.source_list[i].trace_images)
            source_hdu = fits.PrimaryHDU(self.source_list[i].trace_images)

            #Put in the source info
            source_hdu.header["XPOS"] = self.source_list[i].pos[0]
            source_hdu.header["YPOS"] = self.source_list[i].pos[1]

            #only write position errors if they exist. 
            if len(self.source_list[i].pos)>2:
                source_hdu.header["XPOS_ERR"] = self.source_list[i].pos[2]
                source_hdu.header['YPOS_ERR'] = self.source_list[i].pos[3]
            
           

            source_hdu.header["SLIT_LOC"] = self.source_list[i].slit_pos

            #Data reduction status headers for each source
            source_hdu.header["WL_CBRTD"] = (self.source_list[i].lambda_calibrated,"Wavelength Calibrated? status")
            source_hdu.header["POL_CMPD"] = (self.source_list[i].polarization_computed,"Polarization Computed? status")
            source_hdu.header["SPC_XTRD"] = (self.source_list[i].spectra_extracted,"Spectra Extracted? status")
            source_hdu.header["THMB_CUT"] = (self.source_list[i].thumbnails_cut_out,"Thumbnails cut out? status")
            
            
            #Append it to the hdu list
            hdulist.append(source_hdu)
            

            #TODO: Add a fits table extension (or a series of them) to contain the spectra
            #Create a TableHDU for each of the sources
            
            #The source_list attributes, trace_spectra(four separate trace spectra), Q, U, P, theta, are converted into tables of three columns each. Also returns length lists of each array
            t_ts_0,l0=self.make_triplet_table(self.source_list[i].trace_spectra, ['trace_spectra_0 wavelength','D','nm'],
['trace_spectra_0 flux','D','units?'], ['trace_spectra_0 flux error','D','units?'])#trace spectra 0
            t_ts_1,l1=self.make_triplet_table(self.source_list[i].trace_spectra, ['trace_spectra_1 wavelength','D','nm'], ['trace_spectra_1 flux','D','units?'], ['trace_spectra_1 flux error','D','units?'])#trace spectra 1
            t_ts_2,l2=self.make_triplet_table(self.source_list[i].trace_spectra, ['trace_spectra_2 wavelength','D','nm'], ['trace_spectra_2 flux','D','units?'], ['trace_spectra_2 flux error','D','units?'])#trace spectra 2
            t_ts_3,l3=self.make_triplet_table(self.source_list[i].trace_spectra, ['trace_spectra_3 wavelength','D','nm'], ['trace_spectra_3 flux','D','units?'], ['trace_spectra_3 flux error','D','units?'])#trace spectra 3
            
            
            t_Q,lQ=self.make_triplet_table(self.source_list[i].Q, ['Q wavelength','D','nm'], ['Q stokes','D','units?'], ['Q stokes error','D','units?'])               #Q
            
            t_U,lU=self.make_triplet_table(self.source_list[i].U, ['U wavelength','D','nm'], ['U stokes','D','units?'], ['U stokes error','D','units?'])               #U
            
            t_P,lP=self.make_triplet_table(self.source_list[i].P, ['P wavelength','D','nm'], ['P','D','units?'], ['P error','D','units?'])               #P
            
            t_theta,ltheta=self.make_triplet_table(self.source_list[i].theta, ['theta wavelength','D','nm'], ['theta','D','units?'], ['theta error','D','units?'])       #theta
            #tables of 3 columns each have been made
            

            
            #big table gets made
            #the .columns of each three-column-table are added up to form column_list
            column_list= t_ts_0.columns + t_ts_1.columns + t_ts_2.columns + t_ts_3.columns + t_Q.columns + t_U.columns  + t_P.columns + t_theta.columns
           
            #the column_list becomes a quite large fits table called source_tbl_hdu
            source_tbl_hdu=fits.BinTableHDU.from_columns(column_list)

            
            
            #Append it to the hdu list
            hdulist.append(source_tbl_hdu)
            
            length_list=l0+l1+l2+l3+lQ+lU+lP+ltheta  #making a list of the lengths of columns
            #print ('Ending Iteration #',i);
            
            #Creates a header keyword, value, and comment. 
            #The value designates the length the array that would correspond to the column.
            for k in range(len(length_list)):
                #defines keyword string
                header_keyword="TLENG"+str(k+1)
                #defines comment string
                header_comment="Length of "+hdulist[(2*i)+2].data.names[k] 
                
                
                hdulist[(2*i)+2].header[header_keyword]=(length_list[k],header_comment) #defines the keyword with value and comment
                
        #For loop ended    
        #print ('No more iterations');
        
        
         
        
        #Saving a wirc_object (hdulist)
        print("Saving a wirc_object to {}".format(wirc_object_filename));
        hdulist.writeto(wirc_object_filename, overwrite=overwrite)
        
           

    def make_triplet_table(self, array_in, c1list, c2list, c3list):
        #convert array to fits columns and then fits tables. returns a fits table with 3 columns.
        
        #developed to be called by save_wirc_object (the previously listed function)
        
        #first verifies if array_in has information (not None)
        length=[] #initiates list
        if array_in !=None:
                #print ("array_in != None")
                
                #verifies/determines if array_in.ndim is 2 or 3. 
                #if 2
                if array_in.ndim ==2:
                    #print("array_in.ndim ==2");
                    
                    #defines columns, including data
                    c1 = fits.Column(name=c1list[0],format=c1list[1],unit=c1list[2], array=array_in[0,:])
                    c2 = fits.Column(name=c2list[0],format=c2list[1],unit=c2list[2], array=array_in[1,:])
                    c3 = fits.Column(name=c3list[0],format=c3list[1],unit=c3list[2], array=array_in[2,:])
                    
                #if 3
                elif array_in.ndim ==3:
                    #print("array_in.ndim ==3");
                    #finds the extra index from the name (0th item in list, 14th character in string, converted to int)
                    ex_i=int(c1list[0][14])
                    
                    #defines columns, including data
                    c1 = fits.Column(name=c1list[0],format=c1list[1],unit=c1list[2], array=array_in[ex_i,0,:])
                    c2 = fits.Column(name=c2list[0],format=c2list[1],unit=c2list[2], array=array_in[ex_i,1,:])
                    c3 = fits.Column(name=c3list[0],format=c3list[1],unit=c3list[2], array=array_in[ex_i,2,:])
                
                #if array_in is neither ndim, raises warning to user, and leaves columns blank to allow rest of program to run
                else:
                    #print ("Warning: While trying to convert array_in into a 3 column table, array_in.ndim != 2 or 3")
                    
                    #defines columns, not including data
                    c1 = fits.Column(name=c1list[0],format=c1list[1],unit=c1list[2], array=np.array([]))
                    c2 = fits.Column(name=c2list[0],format=c2list[1],unit=c2list[2], array=np.array([]))
                    c3 = fits.Column(name=c3list[0],format=c3list[1],unit=c3list[2], array=np.array([]))
                    
                    
                
                
        #if array_in is None, initiates blank columns        
        else :
                #print ("array_in == None")
                
                #defines columns, not including data
                c1 = fits.Column(name=c1list[0],format=c1list[1],unit=c1list[2], array=np.array([]))
                c2 = fits.Column(name=c2list[0],format=c2list[1],unit=c2list[2], array=np.array([]))
                c3 = fits.Column(name=c3list[0],format=c3list[1],unit=c3list[2], array=np.array([]))
                
        length=[len(c1.array),len(c2.array),len(c2.array)] #defines length list as the length of the arrays given to each column
        
        #returns table equivalent of array_in and corresponding c<#>lists, also returns length list
        return fits.BinTableHDU.from_columns(fits.ColDefs([c1,c2,c3])),length
         
    def table_columns_to_array(self,table_in,prihdr,cil):
        list3columns = [] #initiates a list of arrays representing the columns
   
        if len(cil) ==3: #if there are 3 columns
            
            #appends the padding-removed arrays (from the columns) to the list3columns
            for j in range(len(cil)):
                list3columns.append(table_in.field(cil[j])[0:prihdr['TLENG'+str(cil[j]+1)]])
            
            #stacks the list together to make 2D output array
            array_out=np.stack((list3columns[0],list3columns[1],list3columns[2]))

        elif len(cil) ==12: #if there are 12 columns
            
            for j in range(len(cil)):
                list3columns.append(table_in.field(cil[j])[0:prihdr['TLENG'+str(cil[j]+1)]])
            
            #stacks portion of list together to form 4 2D arrays
            array_a=np.stack((list3columns[0],list3columns[1],list3columns[2]))
            array_b=np.stack((list3columns[3],list3columns[4],list3columns[5]))
            array_c=np.stack((list3columns[6],list3columns[7],list3columns[8]))
            array_d=np.stack((list3columns[9],list3columns[10],list3columns[11]))
            
            #stacks the 2D arrays to form a 3D output array
            array_out=np.stack((array_a,array_b,array_c,array_c),axis=0)
            

        else:
            print ("Warning: column list improper number of columns")
            array_out = np.array([])#None
        return array_out     
    
          
                
    def load_wirc_object(self, wirc_object_filename):
        '''
        Read in the wircpol_object file from a fits file
        '''
        #common indexing notes for save_wirc_object and load_wirc_object:
        #----#(2*i)+1 is a conversion from the index, i, of the source in source_list to the index of the source in hdulist
        #----#(2*i)+2 is a conversion from the index, i, of the source in source_list to the index of the source's corresponding table in hdulist

        #Open the fits file
        hdulist = fits.open(wirc_object_filename)

        #Read in the full image and the primary header
        self.full_image = hdulist[0].data
        self.header = hdulist[0].header

        #What are the calibration filenames?
        self.dark_fn = self.header["DARK_FN"]
        self.flat_fn = self.header["FLAT_FN"]
        self.bp_fn = self.header["BP_FN"]
        self.bkg_fn = self.header["BKG_FN"]

        self.filter_name = self.header['AFT'][0]

        #What's the calibration status?
        self.calibrated = self.header["CALBRTED"]
        self.bkg_subbed = self.header["BKG_SUBD"]

        #How many sources are there
        self.n_sources = self.header["NSOURCES"]

        #Create one source object for each source and append it to source_list
        self.source_list = []

        for i in range(self.n_sources):
            #print ("starting iteration #",i)
            #Extract the source info from the header
            xpos = hdulist[(2*i)+1].header["XPOS"]
            ypos = hdulist[(2*i)+1].header["YPOS"]
            slit_loc = hdulist[(2*i)+1].header["SLIT_LOC"]
            
            #if they are there)
            
            try:
                xpos_err = hdulist[(2*i)+1].header["XPOS_ERR"]
                ypos_err = hdulist[(2*i)+1].header["YPOS_ERR"]
                new_source = wircpol_source([xpos,ypos,xpos_err,ypos_err],slit_loc, i)
                
            except KeyError:
                new_source = wircpol_source([xpos,ypos],slit_loc, i)
                
            
        

            
            new_source.trace_images = hdulist[(2*i)+1].data #finds the i'th source image data in the hdulist
            
            #finds the table data of the TableHDU corresponding to the i'th source
            big_table=hdulist[(2*i)+2].data 
            
            #finds the header of the TableHDU corresponding to the i'th source
            prihdr=hdulist[(2*i)+2].header 
            
            
            
            #finds 3D array for trace_spectra
            new_source.trace_spectra = self.table_columns_to_array(big_table,prihdr,[0,1,2,3,4,5,6,7,8,9,10,11])
            
            #finds 2D array for Q
            new_source.Q = self.table_columns_to_array(big_table,prihdr,[12,13,14])
            
            #finds 2D array for U
            new_source.U = self.table_columns_to_array(big_table,prihdr,[15,16,17])
            
            #finds 2D array for P
            new_source.P = self.table_columns_to_array(big_table,prihdr,[18,19,20])
            
            #finds 2D array for theta
            new_source.theta = self.table_columns_to_array(big_table,prihdr,[21,22,23])
            
            #adjusting source header statuses
            new_source.lambda_calibrated = hdulist[(2*i)+1].header["WL_CBRTD"]#source attribute, later applied to header["WL_CBRTD"]
            new_source.polarization_computed = hdulist[(2*i)+1].header["POL_CMPD"] #source attribute, later applied to header["POL_CMPD"]
            new_source.spectra_extracted = hdulist[(2*i)+1].header["SPC_XTRD"] #source attribute, later applied to header["SPC_XTRD"]
            new_source.thumbnails_cut_out = hdulist[(2*i)+1].header["THMB_CUT"] #source attribute, later applied to header["THMB_CUT"]

                    

            #Append it to the source_list
            self.source_list.append(new_source)
            
            #print ("ending iteration #",i)

            


    def find_sources(self, direct_image_fn = None, threshold_sigma = 5, guess_seeing = 4, plot = False):
        """
        Find the number of sources in the image and create a wircpol_source objects for each one

        Args:
            direct_image_fn - The direct image with no mask or PG. If this is None then we find the sources with an as-of-yet to be determined method. 

        """
        
        if direct_image_fn != None:

            #Open the direct image
            direct_image = fits.open(direct_image_fn)[0].data
            
            #Get the focal plane mask. 
            mask = cross_mask_ns.astype('bool') #What does our mask look like? 

            #Find the sources 
            locations = image_utils.find_sources_in_direct_image(direct_image, mask, threshold_sigma = threshold_sigma, guess_seeing = guess_seeing, plot = plot)

            #How many sources are there? 
            self.n_sources = np.shape(locations[0,:])[0]+1

            #Append all the new objects
            for source in range(self.n_sources):
                self.source_list.append(wircpol_source(locations[source, 0], locations[source,1],source))

        else: 
            print("No direct image filename given. For now we can only find sources automatically in a direct image, so we'll assume that there's a source in the middle slit. If you wish you can add other sources as follows: \n\n > wirc_data.source_list.append(wircpol_source([y,x],slit_pos,wirc_data.n_sources+1) \
            #where slit_pos is '0','1','2' or slitless. \n > wirc_data.n_sources += 1")

            self.source_list.append(wircpol_source([1063,1027],'1',self.n_sources+1))
            self.n_sources = 1
            
        self.header['NSOURCES'] = self.n_sources

    
    def get_source_cutouts(self):
        """
        Get thumbnail cutouts for the spectra of for each source in the image. 
        """

        for source in range(self.n_sources):
            self.source_list[source].get_cutouts(self.full_image, filter_name = self.filter_name, sub_bar = True)



class wircpol_source(object):
    """
    A point-source in a a wircpol_data image    

    Args:
        pos - [x,y] - the location in the image of the source
        slit_pos - Is it in the slit with possible values of [0,1,2,'slitless']


    Attributes:
        trace_images - An array of size [4,N,N], where n is the width of the box, and there is one image for each trace
        trace_spectra - An array of size [4,3, m], where each m-sized spectrum as a wavelength, a flux and a flux error
        pol_spectra - An array of size [3,3, m], where each m-sized spectrum as a wavelength, a flux and a flux error
        calibrated_pol_spectra - An array of size [5,3, m], where each m-sized spectrum as a wavelength, a flux and a flux error
        Q - an array of size 3,m, where each m sized stokes-Q has a wavelength, stokes Q  and Q error
        U - an array of size 3,m, where each m sized stokes-U has a wavelength, stokes U  and U error
        P - an array of size 3,m, where each m sized stokes-Q has a wavelength, P  and P error
        theta - an array of size 3,m, where each m sized stokes-Q has a wavelength, theta  and theta error
        lambda_calibrated - value of associated header["WL_CBRTD"]. designates whether wavelength has been calibrated
        polarization_compute - value of associated header["POL_CMPD"]. designates whether polarization has been computed
        spectra_extracted - value of associated header["SPC_XTRD"]. designates whether spectra has been extracted
        thumbnails_cut_out - value of associated header["THMB_CUT"]. designates whether thumbnails have been cut out
        

    """
    def __init__(self, pos, slit_pos, index):

        #The source position
        self.pos = pos
        #The source locationr relative to the slit
        self.slit_pos = slit_pos

        #The traces of each spectra
        self.trace_images = None

        #The source index (from the parent object)
        self.index = index 

        #Extracted spectra 
        self.trace_spectra = None
        self.pol_spectra = None
        self.Q = None
        self.U = None
        self.P = None
        self.theta = None
    
        #source reduction status?
        self.lambda_calibrated = False #source attribute, later applied to header["WL_CBRTD"]
        self.polarization_computed = False #source attribute, later applied to header["POL_CMPD"]
        self.spectra_extracted = False #source attribute, later applied to header["SPC_XTRD"]
        self.spectra_aligned = False
        self.thumbnails_cut_out = False #source attribute, later applied to header["THMB_CUT"]

    def get_cutouts(self, image, filter_name, sub_bar=True):
        """
        Cutout thumbnails and put them into self.trace_images

        """
        
        self.trace_images = np.array(image_utils.cutout_trace_thumbnails(image, np.expand_dims([self.pos, self.slit_pos],axis=0), flip=False,filter_name = filter_name, sub_bar = sub_bar)[0])
        
        self.thumbnails_cut_out = True #source attribute, later applied to header["THMB_CUT"]

    def plot_cutouts(self, **kwargs):

        fig = plt.figure(figsize = (12,8))

        ax = fig.add_subplot(141)
        plt.imshow(self.trace_images[0,:,:], **kwargs)
        plt.text(5,145,"Top - Left", color='w')

        ax = fig.add_subplot(142)
        plt.imshow(self.trace_images[1,:,:], **kwargs)
        plt.text(5,145,"Bottom - Right", color='w')

        ax = fig.add_subplot(143)
        plt.imshow(self.trace_images[2,:,:], **kwargs)
        plt.text(5,145,"Top - Right", color='w')

        ax = fig.add_subplot(144)
        plt.imshow(self.trace_images[3,:,:], **kwargs)
        plt.text(5,145,"Bottom - Left", color='w')
        
        fig.subplots_adjust(right=0.85)
        cbar_ax = fig.add_axes([0.90, 0.38, 0.03, 0.24])
        plt.colorbar(cax = cbar_ax)

        plt.show()

    def extract_spectra(self, sub_background = False, plot=False, method = 'weightedSum', width_scale=1., diag_mask=False, \
         fitfunction = 'Moffat', sum_method = 'weighted_sum', box_size = 1, poly_order = 4, align = True):
        """
        *method:        method for spectral extraction. Choices are
                            (i) skimage: this is just the profile_line method from skimage. Order for interpolation 
                                            is in skimage_order parameter (fast).
                            (ii) weightedSum: this is 2D weighted sum assuming Gaussian profile. Multiply the PSF with data
                                            and sum for each location along the dispersion direction (fast). The width of the Gaussian
                                            is based on the measured value by 'findTrace'. One can adjust this using the parameter 'width_scale'.
                            (iii) fit_across_trace: this method rotates the trace, loops along the dispersion direction, and fit a profile in the 
                                            spatial direction. The fit function is either 'Moffat' or 'Gaussian'. One can also
                                            select how to extract flux: by summing the fitted model, or the data weighted by the model.
                                            ('model_sum' vs 'weighted_sum'). These are in 'fitfunction' and 'sum_method' parameters.
                                            box_size determine how many columns of pixel we will use. poly_order is the order of polynomial used to
                                            fit the background. 
        """
        print("Performing Spectral Extraction for source {}".format(self.index))

        #call spec_extraction to actually extract spectra
        spectra, spectra_std = spec_utils.spec_extraction(self.trace_images, self.slit_pos, sub_background = sub_background, 
            plot=plot, method=method, width_scale=width_scale, diag_mask=diag_mask, fitfunction = fitfunction, sum_method = sum_method, box_size = box_size, poly_order = poly_order) 
        #if align, then call align_set_of_traces to align 4 traces to the Q plus, using cross-correlation
        for i in spectra:
            plt.plot(i)
        plt.show()
        if align:
            spectra = spec_utils.align_set_of_traces(spectra, spectra[0])
        for i in spectra:
            plt.plot(i)
        plt.show()
        spectra_length = spectra.shape[1]

        self.trace_spectra = np.zeros((4,3,spectra_length))
        self.trace_spectra[:,0,:] = np.arange(spectra_length) #The wavelength axis, to be calibrated later. 
        self.trace_spectra[:,1,:] = spectra
        self.trace_spectra[:,2,:] = spectra_std
        
        self.spectra_extracted = True #source attribute, later applied to header["SPC_XTRD"]
        self.spectra_aligned = align

    def rough_lambda_calibration(self, filter_name="J", method=1, lowcut=0, highcut=-1):
        #Rough wavelength calibration. Will have to get better later!

        """

        lowcut - The lowest pixel to use in the traces
        highcut - The highest pixel to use in the traces 

        #TODO: It would be good to have lowcut and highcut only apply to the calculation, and not affect the data at this point (I think)

        """
        aligned = self.spectra_aligned

        if aligned: #do wavelength calibration to Qp, then apply it to eveerything else
            if method == 1:
                self.trace_spectra[0,0,:] = spec_utils.rough_wavelength_calibration_v1(self.trace_spectra[0,1,:], filter_name)
                self.trace_spectra[1,0,:] = self.trace_spectra[0,0,:]
                self.trace_spectra[2,0,:] = self.trace_spectra[0,0,:]
                self.trace_spectra[3,0,:] = self.trace_spectra[0,0,:]
            if method == 2:
                self.trace_spectra[0,0,:] = spec_utils.rough_wavelength_calibration_v2(self.trace_spectra[0,1,:], filter_name, lowcut=lowcut, highcut=highcut)
                self.trace_spectra[1,0,:] = self.trace_spectra[0,0,:]
                self.trace_spectra[2,0,:] = self.trace_spectra[0,0,:]
                self.trace_spectra[3,0,:] = self.trace_spectra[0,0,:]

        else:
            if method == 1:
                self.trace_spectra[0,0,:] = spec_utils.rough_wavelength_calibration_v1(self.trace_spectra[0,1,:], filter_name)
                self.trace_spectra[1,0,:] = spec_utils.rough_wavelength_calibration_v1(self.trace_spectra[1,1,:], filter_name)
                self.trace_spectra[2,0,:] = spec_utils.rough_wavelength_calibration_v1(self.trace_spectra[2,1,:], filter_name)
                self.trace_spectra[3,0,:] = spec_utils.rough_wavelength_calibration_v1(self.trace_spectra[3,1,:], filter_name)
            

            elif method == 2:
                self.trace_spectra[0,0,:] = spec_utils.rough_wavelength_calibration_v2(self.trace_spectra[0,1,:], filter_name, lowcut=lowcut, highcut=highcut)
                self.trace_spectra[1,0,:] = spec_utils.rough_wavelength_calibration_v2(self.trace_spectra[1,1,:], filter_name, lowcut=lowcut, highcut=highcut)
                self.trace_spectra[2,0,:] = spec_utils.rough_wavelength_calibration_v2(self.trace_spectra[2,1,:], filter_name, lowcut=lowcut, highcut=highcut)
                self.trace_spectra[3,0,:] = spec_utils.rough_wavelength_calibration_v2(self.trace_spectra[3,1,:], filter_name, lowcut=lowcut, highcut=highcut)

        self.lambda_calibrated = True #source attribute, later applied to header["WL_CBRTD"]

    def compute_polarization(self, cutmin=0, cutmax=160):


        wlQp, q, dq, wlUp,u, du = spec_utils.compute_polarization(self.trace_spectra, cutmin=cutmin, cutmax = cutmax)
        
        pol_spectra_length = q.shape[0]
        
        self.Q = np.zeros([3,pol_spectra_length])
        self.U = np.zeros([3,pol_spectra_length])
        
        self.Q[0,:] = wlQp
        self.Q[1,:] = q
        self.Q[2,:] = dq

        self.U[0,:] = wlUp
        self.U[1,:] = u
        self.U[2,:] = du
        
        self.polarization_computed = True #source attribute, later applied to header["POL_CMPD"]

    def plot_trace_spectra(self, with_errors = False, filter_name="J", smooth_size = 1, smooth_ker = 'Gaussian', **kwargs):

        fig = plt.figure(figsize=(7,7))
        labels = ["Top-Left", "Bottom-Right", "Top-Right", "Bottom-left"]
        for i in range(4):
            wl = self.trace_spectra[i,0,:]
            flux = self.trace_spectra[i,1,:]
            err = self.trace_spectra[i,2,:]
            if smooth_size > 1:
                flux = spec_utils.smooth_spectra(flux, smooth_ker, smooth_size)
            if with_errors:
                plt.errobar(wl, flux,yerr = err, label=labels[i], **kwargs)

            else:
                plt.plot(wl, flux, label=labels[i], **kwargs)

        plt.ylabel("Flux [ADU]")

        if self.lambda_calibrated: #plot is not perfectly the same
            plt.xlabel("Wavelength [um]")
            plt.xlim([1.1,1.4]) #wavelength display range
        else:
            plt.xlabel("Wavelength [Arbitrary Unit]")
            plt.xlim([0,225]) #arbitrary unit wavelength display range
        
        plt.legend()
        plt.show()

    def plot_Q_and_U(self, with_errors = False, xlow=1.15, xhigh=1.35, ylow=-0.2, yhigh=0.2, **kwargs):

        fig = plt.figure(figsize=(7,7))

        ax1 = fig.add_subplot(121)
        ax2 = fig.add_subplot(122)
        ax1.set_title("Stokes Q")
        ax2.set_title("Stokes U")

        if with_errors:
            ax1.errorbar(self.Q[0,:], self.Q[1,:],yerr=self.Q[2,:], **kwargs)
            ax2.errorbar(self.U[0,:], self.U[1,:],yerr=self.U[2,:], **kwargs)
        else:
            ax1.plot(self.Q[0,:], self.Q[1,:], **kwargs)
            ax2.plot(self.U[0,:], self.U[1,:], **kwargs)

        ax1.set_ylim(ylow,yhigh)
        ax2.set_ylim(ylow,yhigh)

        if self.lambda_calibrated:
            ax1.set_xlabel("Wavelength [um]")
            ax2.set_xlabel("Wavelength [um]")
            ax1.set_xlim(xlow,xhigh)
            ax2.set_xlim(xlow,xhigh)
        else:
            ax1.set_xlabel("Wavelength [Arbitrary Units]")
            ax2.set_xlabel("Wavelength [Arbitrary Units]")

    # def subtract_pol_bias():

    # def wavelength_calibration():

    # def show_traces():



