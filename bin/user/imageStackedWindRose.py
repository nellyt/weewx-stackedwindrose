# imageStackedWindRose.py
#
# A weeWX generator to generate a polar windrose plot image file based upon
# weeWX archive data.
#
#   Copyright (c) 2013-2017 Gary Roderick           gjroderick<at>gmail.com
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program.  If not, see http://www.gnu.org/licenses/.
#
# Version: 2.1.0                                        Date: 13 March 2017
#
# Revision History
#   13 March 2017       v2.1.0
#       -   fixed error resulting from change to ? signature
#       -   revised these comments
#   15 August 2016      v2.0.2
#       -   reworked imports to use PIL if available
#       -   updated readme/readme.txt
#   9 August 2016       v2.0.1
#       -   fixed typo in install instructions
#   8 August 2016       v2.0.0
#       -   packaged as a standalone weewx extension
#       -   added unit conversion for wind speed (seems it only ever used the
#           archive units)
#       -   restructured the ImageStackedWindRoseGenerator class
#       -   removed a number of unused imports and properties
#       -   various formatting changes, mainly shortening of variable/property
#           names
#   August 2015         v1.2.0
#       -   revised for weeWX 3.2.0
#       -   Fixed issue whereby a fatal error was thrown if
#           imageStackedWindRose could not find the font specified in
#           skin.conf. Error is now trapped and a default system font used
#           instead.
#   10 January 2015     v1.0.0
#       -   rewritten for weeWX 3.0.0
#   1 May 2014          v0.9.3
#       -   fixed issue that arose with weeWX 2.6.3 now allowing use of UTF-8
#           characters in plots
#       -   fixed logic error in code that calculates size of windrose 'petals'
#       -   removed unnecessary import statements
#       -   tweaked windrose size calculations to better cater for labels on
#           the plot
#   30 July 2013        v0.9.1
#       -   revised version number to align with weeWX-WD version numbering
#   20 July 2013        v0.1.0
#       -   initial release
#

import math
import os.path
import syslog
import time
# first try to import from PIL then revert to python-imaging if an error
try:
    from PIL import Image, ImageDraw
except ImportError:
    import Image, ImageDraw

import weewx.reportengine

from datetime import datetime as dt
from weeplot.utilities import get_font_handle
from weeutil.weeutil import accumulateLeaves, option_as_list, TimeSpan
from weewx.units import Converter

STACKED_WINDROSE_VERSION = '3.0.0'

DEFAULT_PETAL_COLORS = ['lightblue', 'blue', 'midnightblue', 'forestgreen',
                        'limegreen', 'green', 'greenyellow']

#=============================================================================
#                    Class ImageStackedWindRoseGenerator
#=============================================================================

class ImageStackedWindRoseGenerator(weewx.reportengine.ReportGenerator):
    """Class to manage the stacked windrose image generator.

    The ImageStackedWindRoseGenerator class is a customised report generator
    that produces polar wind rose plots based upon weewx archive data. The
    generator produces image files that may be used included in a web page, a
    weewx web page template or elsewhere as required.

    The wind rose plot charatcteristics may be controlled through option
    settings in the [Stdreport] [[StackedWindRose]] section of weewx.conf.
    """

    def __init__(self, config_dict, skin_dict, gen_ts,
                 first_run, stn_info, record=None):
        # Initialise my superclass
        super(ImageStackedWindRoseGenerator, self).__init__(config_dict,
                                                            skin_dict,
                                                            gen_ts,
                                                            first_run,
                                                            stn_info,
                                                            record)

        # Get a manager for our archive
        _binding = self.config_dict['StdArchive'].get('data_binding',
                                                      'wx_binding')
        self.archive = self.db_binder.get_manager(_binding)

        # Set a few properties we will need
        self.image_dict = self.skin_dict['ImageStackedWindRoseGenerator']
        self.title_dict = self.skin_dict['Labels']['Generic']
        self.converter = Converter.fromSkinDict(self.skin_dict)

        # Set image attributes
        self.image_width = int(self.image_dict['image_width'])
        self.image_height = int(self.image_dict['image_height'])
        self.image_back_box_color = int(self.image_dict['image_background_box_color'], 0)
        self.image_back_circle_color = int(self.image_dict['image_background_circle_color'], 0)
        self.image_back_range_ring_color = int(self.image_dict['image_background_range_ring_color'], 0)
        self.image_back_image = self.image_dict['image_background_image']

        # Set compass point abbreviations

        _compass = option_as_list(self.skin_dict['Labels'].get('compass_points',
                                                               'N, S, E, W'))
        self.north = _compass[0]
        self.south = _compass[1]
        self.east = _compass[2]
        self.west = _compass[3]

        # Set windrose attributes
        self.plot_border = int(self.image_dict['windrose_plot_border'])
        self.legend_bar_width = int(self.image_dict['windrose_legend_bar_width'])
        self.font_path = self.image_dict['windrose_font_path']
        self.plot_font_size  = int(self.image_dict['windrose_plot_font_size'])
        self.plot_font_color = int(self.image_dict['windrose_plot_font_color'], 0)
        self.legend_font_size  = int(self.image_dict['windrose_legend_font_size'])
        self.legend_font_color = int(self.image_dict['windrose_legend_font_color'], 0)
        self.label_font_size  = int(self.image_dict['windrose_label_font_size'])
        self.label_font_color = int(self.image_dict['windrose_label_font_color'], 0)
        # Look for petal colours, if not defined then set some defaults
        _colors = option_as_list(self.image_dict.get('windrose_plot_petal_colors',
                                                     DEFAULT_PETAL_COLORS))
        _colors = DEFAULT_PETAL_COLORS if len(_colors) < 7 else _colors
        self.petal_colors=[]
        for _color in _colors:
            try:
                # Can it be converted to a number?
                self.petal_colors.append(int(_color, 0))
            except ValueError:  # Cannot convert to a number, assume it is
                                # a colour word so append it as is
                self.petal_colors.append(_color)
        # Get petal width, if not defined then set default to 16 (degrees)
        try:
            self.petal_width = int(self.image_dict['windrose_plot_petal_width'])
        except KeyError:
            self.petal_width = 16
        # Boundaries for speed range bands, these mark the colour boundaries
        # on the stacked bar in the legend. 7 elements only (ie 0, 10% of max,
        # 20% of max...100% of max)
        self.speedFactor = [0.0, 0.1, 0.2, 0.3, 0.5, 0.7, 1.0]

    def run(self):
        """Main entry point to generate the plot(s)."""

        # Generate the image
        self.genWindRosePlots()

    def genWindRosePlots(self):
        """Generate the windrose plots.

        Loop through each 2nd level section (ie [[]]) under
        [ImageStackedWindRoseGenerator] and generate the plot defined by each
        2nd level section.
        """

        # Time period taken to generate plots, set plot count to 0
        t1 = time.time()
        ngen = 0
        # Loop over each time span class (day, week, month, etc.):
        for span in self.image_dict.sections:
            print span
            # Now, loop over all plot names in this time span class:
            for plot in self.image_dict[span].sections:
                print plot
                # Accumulate all options from parent nodes:
                print " %s %s" % (span, plot)
                p_options = accumulateLeaves(self.image_dict[span][plot])
                # Get end time for plot. In order try self.gen_ts, last known
                # good archive time stamp and then current time
                self.p_gen_ts = self.gen_ts
                if not self.p_gen_ts:
                    self.p_gen_ts = self.archive.lastGoodStamp()
                    if not self.p_gen_ts:
                        self.p_gen_ts = time.time()
                # Get the period for the plot, default to 24 hours if no
                # period set
                self.period = p_options.as_int('period') if p_options.has_key('period') else 86400
                # Get the path of the image file we will save
                image_root = os.path.join(self.config_dict['WEEWX_ROOT'],
                                          p_options['HTML_ROOT'])
                # Get image file format. Can use any format PIL can write
                # Default to png
                if p_options.has_key('format'):
                    format = p_options['format']
                else:
                    format = "png"
                 # Get plot style, options : rose, spiral, scatter
                # Default to rose
                if p_options.has_key('plot_type'):
                    self.plot_type = p_options['plot_type']
                else:
                    self.plot_type = "rose"
                print self.plot_type
                # Get legend enable, options : true, false
                # Default to true for rose and spiral, false for scatter
                if p_options.has_key('legend'):
                    self.legend = p_options['legend']
                else:
                    if self.plot_type == "scatter" :
                        self.legend = "false"
                    else :
                        self.legend = "true"
                # Get centre for spiral, options : oldest, newest
                # Default to oldest
                if p_options.has_key('centre'):
                    self.centre = p_options['centre']
                else:
                    self.centre = "oldest"
                # Get marker_style, options : dot, circle, cross, none
                # Default to circle
                if p_options.has_key('marker_style'):
                    marker_style = p_options['marker_style']
                else:
                    marker_style = "circle"
                # Get line_style, 
                # options : straight, radial, none for spiral, default radial
                # option : straight, radial, spoke, none for scatter, default none
                # Default to radial
                if p_options.has_key('line_style'):
                    line_style = p_options['line_style']
                else:
                    if self.plot_type == "spiral" :
                        line_style = "radial"
                    else :
                        line_style = "none"
                # Get line_color, 
                # options : speed, hex color
                # options : age, hex color
                # Default to speed
                if p_options.has_key('line_color'):
                    if p_options['line_color'] == 'speed':
                        line_color = "speed"
                    elif p_options['line_color'] == 'age':
                        line_color = "age"
                    else :
                        line_color = int(p_options['line_color'],0)
                else:
                    if self.plot_type == "scatter" :
                        line_color = "age"
                    else :
                        line_color = "speed"
                # Get marker_color, options : speed, hex color
                # Default to speed
                if p_options.has_key('marker_color'):
                    if p_options['marker_color'] == 'speed':
                        marker_color = "speed"
                    else :
                        marker_color = int(p_options['marker_color'],0)
                else:
                    marker_color = "speed"
                if p_options.has_key('oldest_color'):
                    oldest_color = p_options['oldest_color']
                else:
                    oldest_color = "0xF7FAFF"
                if p_options.has_key('newest_color'):
                    newest_color = p_options['newest_color']
                else:
                    newest_color = "0x00368e"
                if p_options.has_key('axis_label'):
                    axis_label = p_options['axis_label']
                else:
                    axis_label = "%H:%M"
                # Get full file name and path for plot
                img_file = os.path.join(image_root, '%s.%s' % (plot,
                                                               format))
                # Check whether this plot needs to be done at all:
                if self.skipThisPlot(img_file, plot):
                    continue
                # Create the subdirectory that the image is to be put in.
                # Wrap in a try block in case it already exists.
                try:
                    os.makedirs(os.path.dirname(img_file))
                except:
                    pass
                # Loop over each line to be added to the plot.
                for line_name in self.image_dict[span][plot].sections:

                    # Accumulate options from parent nodes.
                    line_options = accumulateLeaves(self.image_dict[span][plot][line_name])

                    # See if a plot title has been explicitly requested.
                    # 'label' used for consistency in skin.conf with
                    # ImageGenerator sections
                    label = line_options.get('label')
                    if label:
                        self.label = unicode(label, 'utf8')
                    else:
                        # No explicit label so set label to nothing
                        self.label = label
                    # See if a time_stamp has been explicitly requested.
                    self.t_stamp = line_options.get('time_stamp')
                    # See if time_stamp location has been explicitly set
                    _location = line_options.get('time_stamp_location')
                    if _location:
                        self.t_stamp_loc = [x.upper() for x in _location]
                    else:
                        self.t_stamp_loc = None
                    # See what SQL variable type to use for this plot and get
                    # corresponding 'direction' type. Can really only plot
                    # windSpeed and windGust, if anything else default to
                    # windSpeed.
                    self.obName = line_options.get('data_type', line_name)
                    if self.obName == 'windSpeed':
                        self.dirName = 'windDir'
                    elif self.obName == 'windGust':
                        self.dirName = 'windGustDir'
                    else:
                        self.obName == 'windSpeed'
                        self.dirName = 'windDir'
                    # Get our data tuples for speed and direction.
                    getSqlVectors_TS = TimeSpan(self.p_gen_ts - self.period + 1,
                                                self.p_gen_ts)
                    (_, time_vec_t_ws_stop, data_speed) = self.archive.getSqlVectors(getSqlVectors_TS,
                                                                                     self.obName)
                    (_, time_vec_t_wd_stop, dir_vec) = self.archive.getSqlVectors(getSqlVectors_TS,
                                                                                  self.dirName)
                    # Convert our speed values to the units we are going to
                    # use in our plot
                    speed_vec = self.converter.convert(data_speed)
                    # Get units for display on legend
                    self.units = self.skin_dict['Units']['Labels'][speed_vec[1]].strip()
                    # Find maximum speed from our data
                    maxSpeed = max(speed_vec[0])
                    # Set upper speed range for our plot, set to a multiple of
                    # 10 for a neater display
                    self.maxSpeedRange = (int(maxSpeed / 10.0) + 1) * 10
                    # Setup 2D list with speed range boundaries in speedList[0]
                    # petal colours in speedList[1]
                    speedList = [[0 for x in range(7)] for x in range(2)]
                    # Store petal colours
                    speedList[1] = self.petal_colors
                    # Loop though each speed range boundary and store in
                    # speedList[0]
                    i = 1
                    while i < 7:
                        speedList[0][i] = self.speedFactor[i] * self.maxSpeedRange
                        i += 1
                    # Setup 2D list for wind direction
                    # windBin[0] represents each of 16 compass directions
                    # ([0] is N, [1] is ENE etc).
                    # windBin[1] holds count of obs in a partiuclr speed range
                    # for given direction
                    windBin = [[0 for x in range(7)] for x in range(17)]
                    # Setup list to hold obs counts for each speed range
                    speedBin = [0 for x in range(7)]
                    # How many obs do we have?
                    samples = len(time_vec_t_ws_stop[0])
                    # Loop through each sample and increment direction counts
                    # and speed ranges for each direction as necessary. 'None'
                    # direction is counted as 'calm' (or 0 speed) and
                    # (by definition) no direction and are plotted in the
                    # 'bullseye' on the plot
                    i = 0
                    while i < samples:
                        if (speed_vec[0][i] is None) or (dir_vec[0][i] is None):
                            windBin[16][6] += 1
                        else:
                            bin = int((dir_vec[0][i] + 11.25) / 22.5) % 16
                            if speed_vec[0][i] > speedList[0][5]:
                                windBin[bin][6] += 1
                            elif speed_vec[0][i] > speedList[0][4]:
                                windBin[bin][5] += 1
                            elif speed_vec[0][i] > speedList[0][3]:
                                windBin[bin][4] += 1
                            elif speed_vec[0][i] > speedList[0][2]:
                                windBin[bin][3] += 1
                            elif speed_vec[0][i] > speedList[0][1]:
                                windBin[bin][2] += 1
                            elif speed_vec[0][i] > 0:
                                windBin[bin][1] += 1
                            else:
                                windBin[bin][0] += 1
                        i += 1
                    # Add 'None' obs to 0 speed count
                    speedBin[0] += windBin[16][6]
                    # Don't need the 'None' counts so we can delete them
                    del windBin[-1]
                    # Now set total (direction independent) speed counts. Loop
                    # through each petal speed range and increment direction
                    # independent speed ranges as necessary
                    j = 0
                    while j < 7:
                        i = 0
                        while i < 16:
                            speedBin[j] += windBin[i][j]
                            i += 1
                        j += 1
                    # Calc the value to represented by outer ring
                    # (range 0 to 1). Value to rounded up to next multiple of
                    # 0.05 (ie next 5%)
                    self.maxRingValue = (int(max(sum(b) for b in windBin)/(0.05 * samples)) + 1) * 0.05
                    # Find which wind rose arm to use to display ring range
                    # labels - look for one that is relatively clear. Only
                    # consider NE, SE, SW and NW preference in order is
                    # SE, SW, NE and NW
                    # Is SE clear?
                    if sum(windBin[6]) / float(samples) <= 0.3 * self.maxRingValue:
                        labelDir = 6        # If so take it
                    else:                   # If not lets loop through the others
                        for i in [10, 2, 14]:
                            # Is SW, NE or NW clear
                            if sum(windBin[i])/float(samples) <= 0.3 * self.maxRingValue:
                                labelDir = i    # If so let's take it
                                break           # And exit for loop
                        else:                   # If none are free then let's
                                                # take the smallest of the four
                            labelCount = samples + 1  # Set max possible number of
                                                    # readings+1
                            i = 2                   # Start at NE
                            for i in [2, 6, 10, 14]:   # Loop through directions
                                # If this direction has fewer obs than previous
                                # best (least)
                                if sum(windBin[i]) < labelCount:
                                    # Set min count so far to this bin
                                    labelCount = sum(windBin[i])
                                    # Set labelDir to this direction
                                    labelDir = i
                    self.labelDir = labelDir
                    # Set up an Image object to hold our windrose plot
                    self.windRoseImageSetup()
                    # Get a Draw object to draw on
                    self.draw = ImageDraw.Draw(self.image)
                    # Set fonts to be used
                    self.plotFont = get_font_handle(self.font_path,
                                                    self.plot_font_size)
                    self.legendFont = get_font_handle(self.font_path,
                                                      self.legend_font_size)
                    self.labelFont = get_font_handle(self.font_path,
                                                     self.label_font_size)
                    # Estimate space requried for the legend
                    textWidth, textHeight = self.draw.textsize("0 (100%)",
                                                               font=self.legendFont)
                    legendWidth = int(textWidth + 2 * self.legend_bar_width + 1.5 * self.plot_border)
                    # Estimate space required for label (if required)
                    textWidth, textHeight = self.draw.textsize("Wind Rose",
                                                          font=self.labelFont)
                    if self.label:
                        labelHeight = int(textWidth+self.plot_border)
                    else:
                        labelHeight=0
                    # Calculate the diameter of the circular plot space in
                    # pixels. Two diameters are calculated, one based on image
                    # height and one based on image width. We will take the
                    # smallest one. To prevent optical distortion for small
                    # plots diameter will be divisible by 22
                    self.roseMaxDiameter = min(int((self.image_height - 2 * self.plot_border - labelHeight / 2) / 22.0) * 22,
                                               int((self.image_width - (2 * self.plot_border + legendWidth)) / 22.0) * 22)
                                               # TODO Alternatively set legend to false to keep common
                                               # TODO Scatter has legendwidth removed in above 
                    if self.image_width > self.image_height:    # If wider than height
                        textWidth, textHeight = self.draw.textsize("W",
                                                                   font=self.plotFont)
                        # x coord of windrose circle origin(0,0) top left corner
                        self.originX = self.plot_border + textWidth + 2 + self.roseMaxDiameter / 2
                        # y coord of windrose circle origin(0,0) is top left corner
                        self.originY = int(self.image_height / 2)
                    else:
                        # x coord of windrose circle origin(0,0) top left corner
                        self.originX = 2 * self.plot_border + self.roseMaxDiameter / 2
                        # y coord of windrose circle origin(0,0) is top left corner
                        self.originY = 2 * self.plot_border + self.roseMaxDiameter / 2
                    
                    if self.plot_type == "spiral":
                        # Calculate which samples will fall on the circular axis marks
                        self.timeLabels = list((0, 0, 0, 0, 0, 0))   # List to hold ring labels, 0=centre, 5=outside
                        self.timeLabels[0] = dt.fromtimestamp(time_vec_t_wd_stop[0][0]).strftime(axis_label).strip()
                        self.timeLabels[1] = dt.fromtimestamp(time_vec_t_wd_stop[0][int(round((samples-1)*1/5))]).strftime(axis_label).strip()
                        self.timeLabels[2] = dt.fromtimestamp(time_vec_t_wd_stop[0][int(round((samples-1)*2/5))]).strftime(axis_label).strip()
                        self.timeLabels[3] = dt.fromtimestamp(time_vec_t_wd_stop[0][int(round((samples-1)*3/5))]).strftime(axis_label).strip()
                        self.timeLabels[4] = dt.fromtimestamp(time_vec_t_wd_stop[0][int(round((samples-1)*4/5))]).strftime(axis_label).strip()
                        self.timeLabels[5] = dt.fromtimestamp(time_vec_t_wd_stop[0][(samples-1)]).strftime(axis_label).strip()
                        print samples
                    
                    # Setup windrose plot. Plot circles, range rings, range
                    # labels, N-S and E-W centre lines and compass pont labels
                    self.windRosePlotSetup()
                    if self.plot_type == "spiral":
                        self.roseRadius =  self.roseMaxDiameter / 2
                        print self.roseRadius
                        print time_vec_t_wd_stop[0][0]
                        print dt.fromtimestamp(time_vec_t_wd_stop[0][0]).strftime("%H:%M").strip()
                        #print self.roseRadius
                        #print samples
                        for layer in range(2):
                            lastx = self.originX
                            lasty = self.originY
                            lasta = int(0)
                            lastr = int(0)
                            for i in range(0, samples):
                                # Loop through each sample
                                # Calculate radius for this time sample
                                # Note assumes equal time periods for each sample
                                # samples is the number of observations
                                # self.period is the time period in seconds, which we dont actually need
                                if self.centre == "newest" : 
                                    i2 = samples - 1 - i
                                else :
                                    # assume oldest
                                    i2 = i
                                self.radius = i2*self.roseRadius/(samples-1) # TODO trap sample = 0 or 1
                                print "%d %d" % (i2, self.radius)
                                # TODO actually radius should be a functio of time, this will then cope with nones/gaps and short set of samples
                                
                                if (dir_vec[0][i] is None):
                                    continue
                                else:
                                    thisa = int(dir_vec[0][i])
                                    ##print "%d %f %f" % (i, self.radius, dir_vec[0][i])
                                    self.y = self.radius*math.cos(math.radians(dir_vec[0][i]))
                                    self.x = self.radius*math.sin(math.radians(dir_vec[0][i]))
                                    if i == 0:
                                        # this is the first sample so previous point must be set to this point
                                        lastx = self.originX + self.x
                                        lasty = self.originY - self.y
                                        lasta = thisa
                                        lastr = self.radius
                                    # Size the bound box
                                    point = (int(self.originX + self.x),
                                            int(self.originY - self.y))
                                    bbox = (int(self.originX + self.x-1),
                                            int(self.originY - self.y-1),
                                            int(self.originX + self.x+1),
                                            int(self.originY - self.y+1))
                                    horline = (int(self.originX + self.x-1),
                                            int(self.originY - self.y),
                                            int(self.originX + self.x+1),
                                            int(self.originY - self.y))
                                    verline = (int(self.originX + self.x),
                                            int(self.originY - self.y-1),
                                            int(self.originX + self.x),
                                            int(self.originY - self.y+1))
                                    vector = (int(lastx),
                                            int(lasty),
                                            int(self.originX + self.x),
                                            int(self.originY - self.y))
                                    
                                    if layer == 1:
                                        # Do Markers
                                        # Decide if markers are line colour or marker colour
                                        if marker_color == "speed" : 
                                            # Makes lines function of speed
                                            #print "  %f" % (speed_vec[0][i])
                                            if (speed_vec[0][i] is None or speed_vec[0][i] == 0):
                                                markercolor = speedList[1][0]
                                            else :
                                                lookup = 5
                                                while lookup >= 0: # TODO Yuk, 7 colours is hard coded
                                                    #print "    %d %f" % (lookup, speedList[0][lookup])
                                                    if speed_vec[0][i] > speedList[0][lookup] :
                                                        markercolor = speedList[1][lookup+1]
                                                        break
                                                    lookup -= 1
                                            #print "  %f %s" % (speed_vec[0][i], markercolor)
                                        else :
                                            # Constant colour
                                            markercolor = marker_color
                                        if marker_style == "dot" :
                                            self.draw.point(point, fill=markercolor)   # Draw the point
                                        elif marker_style == "circle" :
                                            self.draw.ellipse(bbox, outline=markercolor, fill=markercolor)   # Draw the circle
                                        elif marker_style == "cross" :
                                            self.draw.line(horline, fill=markercolor, width=1)   # Draw the cross
                                            self.draw.line(verline, fill=markercolor, width=1)   # Draw the cross
                                        else :
                                            #none
                                            pass
                                    else:
                                        # Layer 0, which is the lines between dots
                                        if line_color == "speed" : 
                                            # Makes lines function of speed
                                            #print "  %f" % (speed_vec[0][i])
                                            if (speed_vec[0][i] is None or speed_vec[0][i] == 0):
                                                linecolor = speedList[1][0]
                                            else :
                                                lookup = 5
                                                while lookup >= 0: # TODO Yuk, 7 colours is hard coded
                                                    #print "    %d %f" % (lookup, speedList[0][lookup])
                                                    if speed_vec[0][i] > speedList[0][lookup] :
                                                        linecolor = speedList[1][lookup+1]
                                                        break
                                                    lookup -= 1
                                            #print "  %f %s" % (speed_vec[0][i], linecolor)
                                        else :
                                            # Constant colour
                                            linecolor = line_color
                                        if line_style == "straight" :
                                            self.draw.line(vector, fill=linecolor, width=1)
                                        elif line_style == "radial" :
                                            ##print "%d %d" % (thisa, lasta)
                                            if (thisa - lasta)%360 <= 180 :
                                                starta = lasta
                                                enda = thisa
                                                anglespan = (thisa - lasta)%360
                                                dir = 1
                                            else:
                                                starta = thisa
                                                enda = lasta
                                                anglespan = (lasta - thisa)%360
                                                dir = -1
                                            a = 0
                                            while a < anglespan:
                                                pointr = lastr + (self.radius - lastr)*a/anglespan
                                                pointx = int(self.originX + pointr*math.sin(math.radians(lasta+(a*dir))) )
                                                pointy = int(self.originY - pointr*math.cos(math.radians(lasta+(a*dir))) )
                                                ##print "  %d %f %d %d" % (a, pointr, pointx, pointy)
                                                vector = (int(lastx), int(lasty), int(pointx), int(pointy))
                                                self.draw.line(vector, fill=linecolor, width=1) # Straight line
                                                #self.draw.point((pointx, pointy),fill=linecolor) # Not needed now we are doing lines
                                                lastx = pointx
                                                lasty = pointy
                                                a += 1
                                            # Draw the last line
                                            vector = (int(lastx), int(lasty), int(self.originX + self.x), int(self.originY - self.y))
                                            self.draw.line(vector, fill=linecolor, width=1) # Draw the final line to end point
                                        else :
                                            # assume line_style == "none"
                                            pass
                                        lastx = self.originX + self.x
                                        lasty = self.originY - self.y
                                        lasta = thisa
                                        lastr = self.radius
                    elif self.plot_type == "scatter":
                        print line_color
                        oldestred = int(oldest_color[2:4],16)
                        oldestgreen = int(oldest_color[4:6],16)
                        oldestblue = int(oldest_color[6:8],16)
                        newestred = int(newest_color[2:4],16)
                        newestgreen = int(newest_color[4:6],16)
                        newestblue = int(newest_color[6:8],16)
                        self.roseRadius =  self.roseMaxDiameter / 2
                        print self.roseRadius
                        print samples
                        print self.maxSpeedRange
                        for layer in range(2):
                            lastx = self.originX
                            lasty = self.originY
                            lasta = int(0)
                            lastr = int(0)
                            for i in range(0, samples):
                                # Loop through each sample
                                # Calculate radius for this time sample
                                if (speed_vec[0][i] is None) or (dir_vec[0][i] is None):
                                    continue
                                else:
                                    # Colour fade algorithm from https://stackoverflow.com/questions/21835739/smooth-color-transition-algorithm
                                    p = i / float(samples-1)
                                    r = int((1.0-p) * oldestred + p * newestred + 0.5)
                                    g = int((1.0-p) * oldestgreen + p * newestgreen + 0.5)
                                    b = int((1.0-p) * oldestblue + p * newestblue + 0.5)
                                    col = '#%02x%02x%02x' % (r, g, b)
                                    self.radius = (speed_vec[0][i]/self.maxSpeedRange)*self.roseRadius
                                    #print "%d %s %f %f" % (i, col, self.radius, speed_vec[0][i])
                                    self.y = self.radius*math.cos(math.radians(dir_vec[0][i]))
                                    self.x = self.radius*math.sin(math.radians(dir_vec[0][i]))
                                    # Size the bound box
                                    point = (int(self.originX + self.x),
                                            int(self.originY - self.y))
                                    bbox = (int(self.originX + self.x-1),
                                            int(self.originY - self.y-1),
                                            int(self.originX + self.x+1),
                                            int(self.originY - self.y+1))
                                    horline = (int(self.originX + self.x-1),
                                            int(self.originY - self.y),
                                            int(self.originX + self.x+1),
                                            int(self.originY - self.y))
                                    verline = (int(self.originX + self.x),
                                            int(self.originY - self.y-1),
                                            int(self.originX + self.x),
                                            int(self.originY - self.y+1))
                                    vector = (int(lastx),
                                            int(lasty),
                                            int(self.originX + self.x),
                                            int(self.originY - self.y))
                                    spoke = (int(self.originX),
                                            int(self.originY),
                                            int(self.originX + self.x),
                                            int(self.originY - self.y))
                                    if layer == 1:
                                        if marker_style == "dot" :
                                            self.draw.point(point, fill=col)   # Draw the point
                                        elif marker_style == "circle" :
                                            self.draw.ellipse(bbox, outline=col, fill=col)   # Draw the circle
                                        elif marker_style == "cross" :
                                            self.draw.line(horline, fill=col, width=1)   # Draw the cross
                                            self.draw.line(verline, fill=col, width=1)   # Draw the cross
                                        else :
                                            #none
                                            pass
                                    else:
                                        # layer == 0 = background
                                        if line_color == "age" :
                                            linecolor = col
                                        else :
                                            linecolor = line_color
                                        thisa = int(dir_vec[0][i])
                                        # option : straight, radial, spoke, none for scatter
                                        if line_style == "spoke" :
                                            self.draw.line(spoke, fill=linecolor, width=1)
                                        elif line_style == "straight" :
                                            self.draw.line(vector, fill=linecolor, width=1)
                                        elif line_style == "radial" :
                                            ##print "%d %d" % (thisa, lasta)
                                            if (thisa - lasta)%360 <= 180 :
                                                starta = lasta
                                                enda = thisa
                                                anglespan = (thisa - lasta)%360
                                                dir = 1
                                            else:
                                                starta = thisa
                                                enda = lasta
                                                anglespan = (lasta - thisa)%360
                                                dir = -1
                                            a = 0
                                            while a < anglespan:
                                                pointr = lastr + (self.radius - lastr)*a/anglespan
                                                pointx = int(self.originX + pointr*math.sin(math.radians(lasta+(a*dir))) )
                                                pointy = int(self.originY - pointr*math.cos(math.radians(lasta+(a*dir))) )
                                                ##print "  %d %f %d %d" % (a, pointr, pointx, pointy)
                                                vector = (int(lastx), int(lasty), int(pointx), int(pointy))
                                                self.draw.line(vector, fill=linecolor, width=1) # Straight line
                                                #self.draw.point((pointx, pointy),fill=linecolor) # Not needed now we are doing lines
                                                lastx = pointx
                                                lasty = pointy
                                                a += 1
                                            # Draw the last line
                                            vector = (int(lastx), int(lasty), int(self.originX + self.x), int(self.originY - self.y))
                                            self.draw.line(vector, fill=linecolor, width=1) # Draw the final line to end point
                                        else :
                                            # assume none
                                            pass
                                        lastx = self.originX + self.x
                                        lasty = self.originY - self.y
                                        lasta = thisa
                                        lastr = self.radius
                        #
                        # End of my scatter
                        #
                    else :
                        # Assume rose
                        # Plot wind rose petals
                        # Each petal is constructed from overlapping pieslices
                        # starting from outside (biggest) and working in (smallest)
                        a = 0   #start at 'North' windrose petal
                        while a < len(windBin): #loop through each wind rose arm
                            s = len(speedList[0]) - 1
                            cumRadius = sum(windBin[a])
                            if cumRadius > 0:
                                armRadius = int((10 * self.roseMaxDiameter * sum(windBin[a])) / (11 * 2.0 * self.maxRingValue * samples))
                                while s > 0:
                                    # Calc radius of current arm
                                    pieRadius = int(round(armRadius * cumRadius/sum(windBin[a]) + self.roseMaxDiameter / 22,0))
                                    # Set bound box for pie slice
                                    bbox = (self.originX-pieRadius,
                                            self.originY-pieRadius,
                                            self.originX+pieRadius,
                                            self.originY+pieRadius)
                                    # Draw pie slice
                                    self.draw.pieslice(bbox,
                                                       int(a * 22.5 - 90 - self.petal_width / 2),
                                                       int(a * 22.5 - 90 + self.petal_width / 2),
                                                       fill=speedList[1][s], outline='black')
                                    cumRadius -= windBin[a][s]
                                    s -= 1  # Move 'in' for next pieslice
                            a += 1  # Next arm
                        # Draw 'bullseye' to represent windSpeed=0 or calm
                        # Produce the label
                        label0 = str(int(round(100.0 * speedBin[0] / sum(speedBin), 0))) + '%'
                        # Work out its size, particularly its width
                        textWidth, textHeight = self.draw.textsize(label0,
                                                                   font=self.plotFont)
                        # Size the bound box
                        bbox = (int(self.originX - self.roseMaxDiameter / 22),
                                int(self.originY - self.roseMaxDiameter / 22),
                                int(self.originX + self.roseMaxDiameter / 22),
                                int(self.originY + self.roseMaxDiameter / 22))
                        self.draw.ellipse(bbox,
                                          outline='black',
                                          fill=speedList[1][0])   # Draw the circle
                        self.draw.text((int(self.originX-textWidth / 2), int(self.originY - textHeight / 2)),
                                       label0,
                                       fill=self.plot_font_color,
                                       font=self.plotFont)   # Display the value
                    # Setup the legend. Draw label/title (if set), stacked bar,
                    # bar labels and units
                    self.legendSetup(speedList, speedBin)
                #Save the file.
                self.image.save(img_file)
                ngen += 1
        syslog.syslog(syslog.LOG_INFO, "imageStackedWindRose: Generated %d images for %s in %.2f seconds" % (ngen,
                                                                                                             self.skin_dict['REPORT_NAME'],
                                                                                                             time.time() - t1))

    def windRoseImageSetup(self):
        """Create image object to draw on."""

        try:
            self.image = Image.open(self.image_back_image)
        except IOError as e:
            self.image = Image.new("RGB",
                                   (self.image_width, self.image_height),
                                   self.image_back_box_color)

    def windRosePlotSetup(self):
        """Draw circular plot background, rings, axes and labels."""

        # Draw speed circles
        if self.plot_type == "scatter" or self.plot_type == "spiral":
            bbMinRad = self.roseMaxDiameter/10.0 # Calc distance between windrose
                                           # range rings.
            delta = 0
            d2 = 0
        else :
            bbMinRad = self.roseMaxDiameter/11 # Calc distance between windrose
                                           # range rings. Note that 'calm'
                                           # bulleye is at centre of plot
                                           # with diameter equal to bbMinRad
                                           # TODO may need 11.0 here also, I needed to make 10.0 for spiral/scatter to avoid integer rounding problems
            delta = 0.5
            d2 = 1
        # Loop through each circle and draw it
        print bbMinRad
        i = 5
        while i > 0:
            bbox = (self.originX - bbMinRad * (i + delta),
                    self.originY - bbMinRad * (i + delta),
                    self.originX + bbMinRad * (i + delta),
                    self.originY + bbMinRad * (i + delta))
            print bbox
            self.draw.ellipse(bbox,
                              outline=self.image_back_range_ring_color,
                              fill=self.image_back_circle_color)
            i -= 1
        #Draw vertical centre line
        self.draw.line([(self.originX, self.originY - self.roseMaxDiameter / 2 - 2), (self.originX, self.originY + self.roseMaxDiameter / 2 + 2)],
                       fill=self.image_back_range_ring_color)
        #Draw horizontal centre line
        self.draw.line([(self.originX - self.roseMaxDiameter / 2 - 2, self.originY), (self.originX + self.roseMaxDiameter / 2 + 2, self.originY)],
                       fill=self.image_back_range_ring_color)
        #Draw N,S,E,W markers
        textWidth, textHeight = self.draw.textsize(self.north, font=self.plotFont)
        self.draw.text((self.originX - textWidth /2, self.originY - self.roseMaxDiameter / 2 - 1 - textHeight),
                       self.north,
                       fill=self.plot_font_color,
                       font=self.plotFont)
        textWidth, textHeight = self.draw.textsize(self.south, font=self.plotFont)
        self.draw.text((self.originX - textWidth /2, self.originY + self.roseMaxDiameter / 2 + 3),
                       self.south,
                       fill=self.plot_font_color,
                       font=self.plotFont)
        textWidth, textHeight = self.draw.textsize(self.west, font=self.plotFont)
        self.draw.text((self.originX - self.roseMaxDiameter / 2 - 1 - textWidth,self.originY-textHeight / 2),
                       self.west,
                       fill=self.plot_font_color,
                       font=self.plotFont)
        textWidth, textHeight = self.draw.textsize(self.east, font=self.plotFont)
        self.draw.text((self.originX + self.roseMaxDiameter / 2 + 1, self.originY - textHeight / 2),
                       self.east,
                       fill=self.plot_font_color,
                       font=self.plotFont)
        # Draw labels on rings
        if self.plot_type == "scatter":
            labelInc = self.maxSpeedRange / 5  # Value increment between rings
        elif self.plot_type == "spiral":
            #TODO this needs to be time !!!!
            labelInc = self.maxRingValue / 5  # Value increment between rings
        else:
            # assume rose
            labelInc = self.maxRingValue / 5  # Value increment between rings
        speedLabels = list((0, 0, 0, 0, 0))   # List to hold ring labels
        i = 1
        while i < 6:
            if self.plot_type == "scatter":
                speedLabels[i - 1] = str(int(round(labelInc * i, 0))) + 'km/h'
            elif self.plot_type == "spiral":
                speedLabels[i - 1] = self.timeLabels[i]
            else:
                # assume rose
                speedLabels[i - 1] = str(int(round(labelInc * i * 100, 0))) + '%'
            i += 1
        # Calculate location of ring labels
        labelAngle = 7 * math.pi / 4 + int(self.labelDir / 4.0) * math.pi / 2
        if self.plot_type == "scatter" or self.plot_type == "spiral":
            labelOffsetX = int(round(self.roseMaxDiameter / 20 * math.cos(labelAngle), 0))
            labelOffsetY = int(round(self.roseMaxDiameter / 20 * math.sin(labelAngle), 0))
        else:
            labelOffsetX = int(round(self.roseMaxDiameter / 22 * math.cos(labelAngle), 0))
            labelOffsetY = int(round(self.roseMaxDiameter / 22 * math.sin(labelAngle), 0))
        # Draw ring labels. Note leave inner ring blank due to lack of space.
        # For clarity each label (except for outside ring) is drawn on a rectangle
        # with background colour set to that of the circular plot
        i = 1 #TODO Spiral has this as 2
        while i < 5:
            textWidth, textHeight = self.draw.textsize(speedLabels[i-1],
                                                       font=self.plotFont)
            self.draw.rectangle(((self.originX + (2 * i + d2) * labelOffsetX - textWidth / 2, self.originY + (2 * i + d2) * labelOffsetY - textHeight / 2),
                                (self.originX + (2 * i + d2) * labelOffsetX + textWidth / 2, self.originY + (2 * i + d2) * labelOffsetY + textHeight / 2)),
                                fill=self.image_back_circle_color)
            self.draw.text((self.originX + (2 * i + d2) * labelOffsetX - textWidth / 2, self.originY + (2 * i + d2) * labelOffsetY - textHeight / 2),
                           speedLabels[i - 1],
                           fill=self.plot_font_color,
                           font=self.plotFont)
            i += 1
        # Draw outside ring label
        textWidth, textHeight = self.draw.textsize(speedLabels[i-1], font=self.plotFont)
        self.draw.text((self.originX + (2 * i + d2) * labelOffsetX - textWidth / 2, self.originY+(2 * i + d2) * labelOffsetY - textHeight / 2),
                       speedLabels[i - 1],
                       fill=self.plot_font_color,
                       font=self.plotFont)

    def legendSetup(self, speedList, speedBin):
        """Draw plot title, legend and time stamp.

        Input Parameters:

            speedList: 2D list with speed range boundaries in speedList[0] and
                       petal colours in speedList[1].
            speedBin: 1D list to hold overal obs count for each speed range.
        """
        # TODO this function actuall does more than just legend, best to split others out into
        # their own function
        
        # set static values
        tWidth, tHeight = self.draw.textsize('E', font=self.plotFont)
        if self.legend == "true" :
            # labX and labY = x,y coords of bottom left of stacked bar.
            # Everything else is relative to this point
            labX = self.originX + self.roseMaxDiameter / 2 + tWidth + 10
            labY = self.originY + self.roseMaxDiameter / 2 - self.roseMaxDiameter / 22
            bulbD = int(round(1.2 * self.legend_bar_width, 0))
            # draw stacked bar and label with values/percentages
            i = 6
            while i>0:
                self.draw.rectangle(((labX, labY - (0.85 * self.roseMaxDiameter * self.speedFactor[i])), (labX + self.legend_bar_width, labY)),
                                    fill=speedList[1][i],
                                    outline='black')
                tWidth, tHeight = self.draw.textsize(str(speedList[0][i]), font=self.legendFont)
                self.draw.text((labX + 1.5 * self.legend_bar_width, labY - tHeight / 2 - (0.85 * self.roseMaxDiameter * self.speedFactor[i])),
                               str(int(round(speedList[0][i], 0))) + ' (' + str(int(round(100 * speedBin[i]/sum(speedBin), 0))) + '%)',
                               fill=self.legend_font_color,
                               font=self.legendFont)
                i -= 1
            tWidth, tHeight = self.draw.textsize(str(speedList[0][0]), font=self.legendFont)
            # Draw 'calm' or 0 speed label and %
            self.draw.text((labX + 1.5 * self.legend_bar_width, labY - tHeight / 2 - (0.85 * self.roseMaxDiameter * self.speedFactor[0])),
                           str(speedList[0][0]) + ' (' + str(int(round(100.0 * speedBin[0] / sum(speedBin), 0))) + '%)',
                           fill=self.legend_font_color,
                           font=self.legendFont)
            tWidth, tHeight = self.draw.textsize('Calm', font=self.legendFont)
            self.draw.text((labX - tWidth - 2, labY - tHeight / 2 - (0.85 * self.roseMaxDiameter * self.speedFactor[0])),
                           'Calm',
                           fill=self.legend_font_color,
                           font=self.legendFont)
            # draw 'calm' bulb on bottom of stacked bar
            bbox = (labX - bulbD / 2 + self.legend_bar_width / 2,
                    labY - self.legend_bar_width / 6,
                    labX + bulbD / 2 + self.legend_bar_width / 2,
                    labY - self.legend_bar_width / 6 + bulbD)
            self.draw.ellipse(bbox, outline='black', fill=speedList[1][0])
            # draw legend title
            if self.obName == 'windGust':
                titleText = 'Gust Speed'
            else:
                titleText = 'Wind Speed'
            tWidth, tHeight = self.draw.textsize(titleText, font=self.legendFont)
            self.draw.text((labX + self.legend_bar_width / 2 - tWidth / 2, labY - 5 * tHeight / 2 - (0.85 * self.roseMaxDiameter)),
                           titleText,
                           fill=self.legend_font_color,
                           font=self.legendFont)
            # draw legend units label
            tWidth, tHeight = self.draw.textsize('(' + self.units + ')', font=self.legendFont)
            self.draw.text((labX + self.legend_bar_width / 2 - tWidth / 2, labY - 3 * tHeight / 2 - (0.85 * self.roseMaxDiameter)),
                           '(' + self.units + ')',
                           fill=self.legend_font_color,
                           font=self.legendFont)
        # draw plot title (label) if any
        if self.label:
            tWidth, tHeight = self.draw.textsize(self.label, font=self.labelFont)
            try:
                self.draw.text((self.originX-tWidth / 2, tHeight / 2),
                               self.label,
                               fill=self.label_font_color,
                               font=self.labelFont)
            except UnicodeEncodeError:
                self.draw.text((self.originX - tWidth / 2, tHeight / 2),
                               self.label.encode("utf-8"),
                               fill=self.label_font_color,
                               font=self.labelFont)
        # draw plot time stamp if any
        if self.t_stamp:
            t_stamp_text = dt.fromtimestamp(self.p_gen_ts).strftime(self.t_stamp).strip()
            tWidth, tHeight = self.draw.textsize(t_stamp_text, font=self.labelFont)
            if self.t_stamp_loc != None:
                if 'TOP' in self.t_stamp_loc:
                    t_stampY = self.plot_border + tHeight
                else:
                    t_stampY = self.image_height-self.plot_border - tHeight
                if 'LEFT' in self.t_stamp_loc:
                    t_stampX = self.plot_border
                elif ('CENTER' in self.t_stamp_loc) or ('CENTRE' in self.t_stamp_loc):
                    t_stampX = self.originX - tWidth / 2
                else:
                    t_stampX = self.image_width - self.plot_border - tWidth
            else:
                t_stampY = self.image_height - self.plot_border - tHeight
                t_stampX = self.image_width - self.plot_border - tWidth
            self.draw.text((t_stampX, t_stampY), t_stamp_text,
                           fill=self.legend_font_color,
                           font=self.legendFont)
        if self.plot_type == "spiral":
            # Display Direction in spiral plots
            if self.centre == "newest" :
                t_stamp_text = "Newest in Center"
            else :
                t_stamp_text = "Oldest in Center " + self.timeLabels[0]
            tWidth, tHeight = self.draw.textsize(t_stamp_text, font=self.labelFont)
            if self.t_stamp_loc != None:
                if 'TOP' in self.t_stamp_loc:
                    t_stampY = self.plot_border + tHeight
                else:
                    t_stampY = self.image_height-self.plot_border - tHeight
                if 'LEFT' in self.t_stamp_loc:
                    t_stampX = self.image_width - self.plot_border - tWidth
                elif ('CENTER' in self.t_stamp_loc) or ('CENTRE' in self.t_stamp_loc):
                    t_stampX = self.originX - tWidth / 2
                    # TODO CANT DO THIS ONE
                else:
                    # Assume RIGHT
                    t_stampX = self.plot_border
            else:
                t_stampY = self.image_height - self.plot_border - tHeight
                t_stampX = self.image_width - self.plot_border - tWidth
            self.draw.text((t_stampX, t_stampY), t_stamp_text,
                           fill=self.legend_font_color,
                           font=self.legendFont)

    def skipThisPlot(self, img_file, plotname):
        """Determine whether the plot is to be skipped or not.

        Successive report cyles will likely produce a windrose that,
        irrespective of period, would be different to the windrose from the
        previous report cycle. In most cases the changes are insignificant so,
        as with the weewx graphical plots, long period plots are generated
        less frequently than shorter period plots. Windrose plots will be
        skipped if:
            (1) no period was specified (need to put entry in syslog)
            (2) plot length is greater than 30 days and the plot file is less
                than 24 hours old
            (3) plot length is greater than 7 but less than 30 day and the plot
                file is less than 1 hour old

        On the other hand, a windrose must be generated if:
            (1) it does not exist
            (2) it is 24 hours old (or older)

        These rules result in windrose plots being generated:
            (1) if an existing plot does not exist
            (2) an existing plot exists but it is older than 24 hours
            (3) every 24 hours when period > 30 days (2592000 sec)
            (4) every 1 hour when period is > 7 days (604800 sec) but
                <= 30 days (2592000 sec)
            (5) every report cycle when period < 7 days (604800 sec)

        Input Parameters:

            img_file: full path and filename of plot file
            plotname: name of plot

        Returns:
            True if plot is to be generated, False if plot is to be skipped.
        """

        # Images without a period must be skipped every time and a syslog
        # entry added. This should never occur, but....
        if self.period is None:
            syslog.syslog(syslog.LOG_INFO, "imageStackedWindRose: Plot " +
                                            plotname +
                                            " ignored, no period specified")
            return True

        # The image definitely has to be generated if it doesn't exist.
        if not os.path.exists(img_file):
            return False

        # If the image is older than 24 hours then regenerate
        if self.p_gen_ts - os.stat(img_file).st_mtime >= 86400:
            return False

        # If period > 30 days and the image is less than 24 hours old then skip
        if self.period > 2592000 and self.p_gen_ts - os.stat(img_file).st_mtime < 86400:
            return True

        # If period > 7 days and the image is less than 1 hour old then skip
        if self.period >= 604800 and self.p_gen_ts - os.stat(img_file).st_mtime < 3600:
            return True

        # Otherwise we must regenerate
        return False
