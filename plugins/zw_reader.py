"""
ZW data reader plugin.
"""

import numpy as np
from datetime import datetime
import struct
import os
import logging
from obspy import Trace, UTCDateTime, Stream

from plugins.base_reader import DataReader

logger = logging.getLogger(__name__)

class ZWHeader:
    """ZW file header parser."""
    
    def __init__(self):
        self.byteCounter = 0
        
    def read_header(self, file):
        """Read header from file."""
        self.head = hex(self._read_ushort16(file))
        self.sps = self._read_ushort16(file)
        self.stationNum = self._read_ushort16(file)
        self.reserve = self._read_uchar8(file)
        self.signal4G = self._read_uchar8(file)
        self.x = self._read_float32(file)
        self.y = self._read_float32(file)
        self.z = self._read_float32(file)
        self.fileVersion = self._read_uchar8(file)
        self.rainSensor = self._read_uchar8(file)
        self.meteorologySensor = self._read_uchar8(file)
        self.soliSensor = self._read_uchar8(file)
        self.kpa = self._read_float32(file)
        self.lux = self._read_uint32(file)
        self.rainfall = self._read_float32(file)
        self.temperature = self._read_float32(file)
        self.humidity = self._read_float32(file)
        self.soilTemperature = self._read_float32(file)
        self.soilMoisture = self._read_float32(file)
        self.solarBattery = self._read_float32(file)
        self.batteryVoltage = self._read_float32(file)
        self.waterLevel = self._read_float32(file)
        self.smartPowerTemperature = self._read_short16(file)
        self.smartPowerVoltage = self._read_ushort16(file)
        self.smartPowerChargeCurrent = self._read_float32(file)
        self.smartPowerDishargeCurrent = self._read_float32(file)
        self.speedSensorPeriod = self._read_float32(file)
        self.speedSensorDamp = self._read_float32(file)
        self.speedSensorSensitivity = self._read_float32(file)
        self.accelerometerSensitivity = self._read_float32(file)
        self.windSpeed = self._read_ushort16(file)
        self.windDirection = self._read_uchar8(file)
        self.windSensorCondition = self._read_uchar8(file)
        self.smartPowerOnOff = self._read_uchar8(file)
        self.timeZone = self._read_char8(file)
        self.dataType = self._read_uchar8(file)
        self.reserve2 = self._read_uchar8(file)
        self.year = self._read_ushort16(file)
        self.month = self._read_uchar8(file)
        self.day = self._read_uchar8(file)
        self.hour = self._read_uchar8(file)
        self.minute = self._read_uchar8(file)
        self.second = self._read_uchar8(file)
        self.storage = self._read_uchar8(file)
        self.basecount = self._read_basecount(file)
        
    def _read_ushort16(self, file):
        """Read unsigned short (16-bit)."""
        self.byteCounter += 2
        return struct.unpack('<H', file.read(2))[0]
        
    def _read_uchar8(self, file):
        """Read unsigned char (8-bit)."""
        self.byteCounter += 1
        return struct.unpack('<B', file.read(1))[0]
        
    def _read_uint32(self, file):
        """Read unsigned int (32-bit)."""
        self.byteCounter += 4
        return struct.unpack('<I', file.read(4))[0]
        
    def _read_float32(self, file):
        """Read float (32-bit)."""
        self.byteCounter += 4
        return struct.unpack('<f', file.read(4))[0]
        
    def _read_short16(self, file):
        """Read short (16-bit)."""
        self.byteCounter += 2
        return struct.unpack('<h', file.read(2))[0]
        
    def _read_char8(self, file):
        """Read char (8-bit)."""
        self.byteCounter += 1
        return struct.unpack('<b', file.read(1))[0]
        
    def _read_basecount(self, file):
        """Read basecount values."""
        if self.dataType == 0:
            num_ints = 9
        elif self.dataType == 1:
            num_ints = 6
        else:
            num_ints = 3
            
        self.byteCounter += num_ints * 4
        return struct.unpack(f'<{num_ints}i', file.read(num_ints * 4))

class ZWReader(DataReader):
    """Reader for ZW format files."""
    
    def read(self, file_path: str) -> Stream:
        """Read data from a ZW file.
        
        Args:
            file_path: Path to the ZW file
            
        Returns:
            ObsPy Stream object containing the data traces
        """
        header = ZWHeader()
        
        with open(file_path, 'rb') as f:
            # Read header
            header.read_header(f)
            
            # Get sampling rate and sensitivity
            sample_rate = header.sps
            sensitivity = np.float64(header.speedSensorSensitivity)
            print(sensitivity)
            # Initialize data array
            vel_all = None
            first_chunk = True
            
            # Skip unsupported data types
            if header.dataType in [3, 4]:
                logger.error(f"Unsupported data type: {header.dataType}")
                return None
                
            # Determine number of components based on data type
            if header.dataType == 0:
                num_ints = 3
            elif header.dataType == 1:
                num_ints = 2
            else:
                num_ints = 1
                
            # Read data chunks
            while True:
                # Read chunk header
                chunk_header = f.read(4 * 9)
                if len(chunk_header) != 4 * 9:
                    break
                    
                # Read bit sizes
                bitsize = struct.unpack(f'{num_ints}B', f.read(num_ints))
                for bit in bitsize:
                    if bit not in (8, 16, 24, 32):
                        raise ValueError(f"Unsupported bit size: {bit}")
                        
                # Calculate data sizes
                if header.dataType == 0:
                    bytes_per_datapoint1 = bitsize[0] // 8
                    total_bytes_pass1 = bytes_per_datapoint1 * sample_rate * 3
                    bytes_per_datapoint2 = bitsize[2] // 8
                    total_bytes_pass2 = bytes_per_datapoint2 * sample_rate * 3
                    bytes_per_datapoint = bitsize[1] // 8
                    total_bytes_pass = bytes_per_datapoint * sample_rate * 3
                elif header.dataType == 1:
                    total_bytes_pass1 = 0
                    bytes_per_datapoint2 = bitsize[1] // 8
                    total_bytes_pass2 = bytes_per_datapoint2 * sample_rate * 3
                    bytes_per_datapoint = bitsize[0] // 8
                    total_bytes_pass = bytes_per_datapoint * sample_rate * 3
                else:
                    total_bytes_pass1 = 0
                    total_bytes_pass2 = 0
                    bytes_per_datapoint = bitsize[0] // 8
                    total_bytes_pass = bytes_per_datapoint * sample_rate * 3
                    
                # Read first pass data
                data1 = f.read(total_bytes_pass1)
                if len(data1) != total_bytes_pass1:
                    break
                    
                # Read velocity data
                vel = f.read(total_bytes_pass)
                if len(vel) != total_bytes_pass:
                    break
                    
                # Parse velocity components
                vel_e = [int.from_bytes(vel[3*i*bytes_per_datapoint:3*i*bytes_per_datapoint+bytes_per_datapoint], 
                                      byteorder='little', signed=True) 
                        for i in range(sample_rate)]
                vel_n = [int.from_bytes(vel[(3*i+1)*bytes_per_datapoint:(3*i+1)*bytes_per_datapoint+bytes_per_datapoint], 
                                      byteorder='little', signed=True) 
                        for i in range(sample_rate)]
                vel_z = [int.from_bytes(vel[(3*i+2)*bytes_per_datapoint:(3*i+2)*bytes_per_datapoint+bytes_per_datapoint], 
                                      byteorder='little', signed=True) 
                        for i in range(sample_rate)]
                
                # Stack velocity components
                if first_chunk:
                    vel_all = np.array([vel_e, vel_n, vel_z])
                    first_chunk = False
                else:
                    new_vel = np.stack((vel_e, vel_n, vel_z), axis=0)
                    vel_all = np.hstack((vel_all, new_vel))
                    
                # Read second pass data
                data2 = f.read(total_bytes_pass2)
                if len(data2) != total_bytes_pass2:
                    break
                    
            # Set basecount values
            if header.dataType == 0:
                basecount_e = header.basecount[3]
                basecount_n = header.basecount[4]
                basecount_z = header.basecount[5]
            else:
                basecount_e = header.basecount[0]
                basecount_n = header.basecount[1]
                basecount_z = header.basecount[2]
                
            if vel_all is not None:
                vel_all[0, 0] = basecount_e
                vel_all[1, 0] = basecount_n
                vel_all[2, 0] = basecount_z
                
                # Convert to physical units using sensitivity
                #vel_all = vel_all * sensitivity
                vel_all[0,:]=np.cumsum(vel_all[0,:])*1
                vel_all[1,:]=np.cumsum(vel_all[1,:])*1
                vel_all[2,:]=np.cumsum(vel_all[2,:])*1
                
            else:
                vel_all = np.zeros((3, 1))
                
        # Create UTCDateTime object for start time
        start_time = UTCDateTime(
            year=header.year, month=header.month, day=header.day,
            hour=header.hour, minute=header.minute, second=header.second
        )
        print(vel_all[0][123])
        
        # Create Stream object
        st = Stream()
        
        # Create common stats dictionary
        stats = {
            'network': '',  # Add network code if available
            'station': str(header.stationNum),
            'location': '',  # Add location code if available
            'sampling_rate': sample_rate,
            'starttime': start_time,
        }
        
        # Add traces for each component
        components = {'E': 0, 'N': 1, 'Z': 2}
        for comp, idx in components.items():
            trace_stats = stats.copy()
            trace_stats['channel'] = f'BH{comp}'  # Broadband High-gain seismometer
            trace_stats['sensitivity'] = sensitivity
            
            tr = Trace(
                data=vel_all[idx] if vel_all is not None else np.zeros(1),
                header=trace_stats
            )
            st.append(tr)
        
        return st
    

    def read_header(self, file_path: str) -> Stream:
        """Read header from a ZW file.
        
        Args:
            file_path: Path to the ZW file
            
        Returns:
            ObsPy Stream object containing the traces of header
        """
        header = ZWHeader()
        
        with open(file_path, 'rb') as f:
            # Read header
            header.read_header(f)
            
            
            # Skip unsupported data types
            if header.dataType in [3, 4]:
                logger.error(f"Unsupported data type: {header.dataType}")
                return None
                
        start_time = UTCDateTime(
            year=header.year, month=header.month, day=header.day,
            hour=header.hour, minute=header.minute, second=header.second
        )   
        # Create Stream object
        st = Stream()
        
        # Create common stats dictionary
        stats = {
            'network': '',  # Add network code if available
            'station': str(header.stationNum),
            'location': '',  # Add location code if available
            'sampling_rate': header.sps,
            'starttime': start_time,
        }
        
        # Add traces for each component
        components = {'E': 0, 'N': 1, 'Z': 2}
        for comp, idx in components.items():
            trace_stats = stats.copy()
            trace_stats['channel'] = f'BH{comp}'  # Broadband High-gain seismometer
            
            
            tr = Trace(header=trace_stats )
            st.append(tr)
        
        return st
            
    def write(self, file_path: str, stream: Stream):
        """Write data to a ZW file.
        
        Args:
            file_path: Path to save the ZW file
            stream: ObsPy Stream object containing the data to write
        """
        raise NotImplementedError("Writing ZW files is not yet supported")
        
    def get_format_name(self) -> str:
        """Get name of data format.
        
        Returns:
            Format name as string
        """
        return "ZW" 