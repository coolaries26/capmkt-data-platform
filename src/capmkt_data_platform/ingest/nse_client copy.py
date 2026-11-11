import os
from datetime import datetime, timedelta
import zipfile
import requests
import logging

LOG_DIR = r"c:\alsgit\capmkt_data_platform\logs"
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(level=logging.INFO, handlers=[
    logging.FileHandler(os.path.join(LOG_DIR, "nse_downloader.log")),
    logging.StreamHandler()
])

def download_archive_zips(start_date_str, end_date_str, save_directory):
    """
    Downloads daily zip files from a website for a given date range.
    Filters out or flags empty zip files (size == 22 bytes).
    """
    # 1. Setup target directory
    if not os.path.exists(save_directory):
        os.makedirs(save_directory)
        logging.info(f"Created target directory: {save_directory}")

    # 2. Parse string dates into datetime objects
    start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
    end_date = datetime.strptime(end_date_str, "%Y-%m-%d")
    
    current_date = start_date
    total_days = (end_date - start_date).days + 1
    
    logging.info(f"Starting download for {total_days} days of data...")
    logging.info("-" * 60)
    # Mimic a standard Windows Google Chrome browser session
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive'
    }
    # 3. Iterate through every single day in the range
    while current_date <= end_date:
        # Format the date into yyyymmdd
        date_suffix = current_date.strftime("%Y%m%d")
        
        # Build URLs and local target paths
        url = f"https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{date_suffix}_F_0000.csv.zip"
        logging.info(f"[{date_suffix}] Attempting to download from: {url}")
        file_name = f"BhavCopy_NSE_CM_0_0_0_{date_suffix}_F_0000.csv.zip"
        local_path = os.path.join(save_directory, file_name)
        
        try:
            # Stream the file rather than loading everything into memory at once
            response = requests.get(url, headers=headers, stream=True, timeout=15)
            
            # Check if the website actually found the file (HTTP 200 OK)
            if response.status_code == 200:
                # Get total content size from header, or evaluate the raw content length
                content = response.content
                file_size = len(content)
                
                # Check for an empty zip frame (22 bytes)
                if file_size == 22:
                    logging.info(f"[{date_suffix}] Empty ZIP detected (22 bytes). Saving to: {local_path}")
                else:
                    logging.info(f"[{date_suffix}] Valid ZIP found ({file_size} bytes). Saving to: {local_path}")
#                    sleep(0.5)  # Optional: slight delay to avoid overwhelming the server
                # Write the binary data to your local folder
                with open(local_path, 'wb') as f:
                    f.write(content)
###
                    # Create a specific sub-folder for extracting this specific day's files
                    # e.g., C:\my_folder\my_file\extracted_20261001
                    extract_sub_dir = os.path.join(
                        save_directory, f"extracted"
                    )

                    try:
                        # Unzip the contents
                        with zipfile.ZipFile(local_path, "r") as zip_ref:
                            zip_ref.extractall(extract_sub_dir)
                        print(f"       -> Extracted successfully to: {extract_sub_dir}")
                    except zipfile.BadZipFile:
                        print(
                            f"       -> [Warning] File saved but failed to unzip. File might be corrupted."
                        )

###
                    
            elif response.status_code == 404:
                logging.warning(f"[{date_suffix}] File not found on server (404 Error). Skipping.")
            else:
                logging.error(f"[{date_suffix}] Failed to download. Server returned status: {response.status_code}")
                
        except requests.exceptions.RequestException as e:
            logging.error(f"[{date_suffix}] Network error encountered: {e}")
            
        # Move forward by exactly 1 day
        current_date += timedelta(days=1)

    logging.info("-" * 60)
    logging.info("Download task completed.")

# --- Configuration & Run ---
if __name__ == "__main__":
    # Define your parameters here
    START = "2025-01-01"            # Adjust the timeframe as needed
    END = "2026-11-07"              # One full month of coverage
    TARGET_DIR = r"c:\alsgit\capmkt_data_platform\data\landing"  
    
    download_archive_zips(START, END, TARGET_DIR)
