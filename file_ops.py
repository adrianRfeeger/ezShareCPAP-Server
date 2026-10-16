# file_ops.py
import datetime
import re
import requests
import bs4
import urllib.parse
import logging
from tempfile import NamedTemporaryFile
import pathlib
import os
import time

logger = logging.getLogger(__name__)

def recursive_traversal(ezshare_instance, url, dir_path, total_files, processed_files, is_running):
    """
    Recursively traverse directories to list and download files.

    :param ezshare_instance: Instance of the main application containing settings and states.
    :param url: URL of the directory to traverse.
    :param dir_path: Local directory path to store the files.
    :param total_files: Total number of files expected to be processed.
    :param processed_files: Count of files already processed.
    :param is_running: Function to check if the process should continue running.
    :return: Updated count of processed files.
    """
    visited = getattr(ezshare_instance, '_download_visited', set())
    ezshare_instance._download_visited = visited
    if url in visited or len(visited) > 10000:
        ezshare_instance.transfer_failed = True
        return processed_files
    visited.add(url)
    files, dirs = list_dir(ezshare_instance, url)
    if files is None and dirs is None:
        ezshare_instance.update_status('Unable to retrieve directory listing. Connection issue suspected.', 'error')
        ezshare_instance.transfer_failed = True
        return processed_files
    processed_files = check_files(ezshare_instance, files, url, dir_path, total_files, processed_files, is_running)
    processed_files = check_dirs(ezshare_instance, dirs, url, dir_path, total_files, processed_files, is_running)
    return processed_files

def list_dir(ezshare, url):
    """
    Fetch and parse directory listing from the given URL.

    :param ezshare: Instance of the main application containing settings and states.
    :param url: URL of the directory to list.
    :return: Tuple of (files, directories).
    """
    try:
        response = ezshare.session.get(url, timeout=5)
        response.raise_for_status()
        soup = bs4.BeautifulSoup(response.text, 'html.parser')
        origin = urllib.parse.urlparse(url)
        for link in soup.select('pre a[href]'):
            target = urllib.parse.urlparse(urllib.parse.urljoin(url, link['href']))
            if (target.scheme, target.netloc) != (origin.scheme, origin.netloc):
                raise ValueError('Directory link leaves card origin')
        files, dirs = parse_directory_listing(ezshare, soup)
        if not hasattr(ezshare, '_listing_fingerprints'):
            ezshare._listing_fingerprints = {}
            ezshare._remote_sizes = {}
        ezshare._listing_fingerprints[url] = soup.find('pre').get_text()
        for link in soup.select('pre a[href]'):
            tail = ''.join(str(part) for part in link.next_siblings).split('\n')[0].strip()
            size = re.fullmatch(r'(\d+)(?:\s*[Bb](?:ytes)?)?', tail)
            if size:
                query = urllib.parse.urlparse(link['href']).query
                ezshare._remote_sizes[(url, query)] = int(size.group(1))
        return files, dirs
    except (requests.RequestException, ValueError) as e:
        logger.error(f"Error fetching directory listing from {url}: {e}")
        return None, None

def parse_directory_listing(ezshare, soup):
    """
    Parse the HTML directory listing to separate files and directories.

    :param ezshare: Instance of the main application containing settings and states.
    :param soup: BeautifulSoup object containing the parsed HTML.
    :return: Tuple of (files, directories).
    """
    files = []
    dirs = []
    
    # Find the <pre> tag
    pre_tag = soup.find('pre')
    
    # Check if <pre> tag exists
    if pre_tag is None:
        logging.error("No <pre> tag found in the HTML response.")
        raise ValueError('Invalid directory listing: missing pre element')
    
    if not pre_tag.find('a'):
        raise ValueError('Unrecognized empty listing; refusing to report success')

    pre_text = pre_tag.decode_contents()  # Extract content from <pre> tag
    lines = pre_text.split('\n')  # Split the content by lines

    for line in lines:
        if line.strip():  # Check if the line is not empty
            parts = line.rsplit(maxsplit=2)  # Split the line into parts
            modifypart = parts[0].replace('- ', '-0').replace(': ', ':0')  # Fix timestamp formatting
            regex_pattern = r'\d*-\d*-\d*\s*\d*:\d*:\d*'  # Regex pattern to match the timestamp
            match = re.search(regex_pattern, modifypart)  # Search for the timestamp
            file_ts = datetime.datetime.strptime(match.group(), '%Y-%m-%d %H:%M:%S').timestamp() if match else 0  # Convert to timestamp
            
            # Parse the line as HTML to extract the link
            soupline = bs4.BeautifulSoup(line, 'html.parser')
            link = soupline.a
            if link:
                link_text = link.get_text(strip=True)  # Get the link text
                link_href = link['href']  # Get the href attribute of the link
                
                if '/' in link_text or '\\' in link_text or '\x00' in link_text:
                    raise ValueError('Unsafe remote name')

                # Ignore files that should be ignored or hidden
                if link_text in ezshare.ignore or link_text.startswith('.'):
                    continue
                
                # Parse the URL
                parsed_url = urllib.parse.urlparse(link_href)
                
                # Check if the link is for a file or directory
                if parsed_url.path.endswith('download'):
                    files.append((link_text, parsed_url.query, file_ts))  # Add file to the list
                elif parsed_url.path.endswith('dir'):
                    dirs.append((link_text, link_href))  # Add directory to the list
    
    return files, dirs

def check_files(ezshare_instance, files, url, dir_path, total_files, processed_files, is_running):
    """
    Process each file in the list, downloading if necessary.

    :param ezshare_instance: Instance of the main application containing settings and states.
    :param files: List of files to process.
    :param url: URL of the directory containing the files.
    :param dir_path: Local directory path to store the files.
    :param total_files: Total number of files expected to be processed.
    :param processed_files: Count of files already processed.
    :param is_running: Function to check if the process should continue running.
    :return: Updated count of processed files.
    """
    for filename, file_url, file_ts in files:
        if not is_running():
            ezshare_instance.update_status('Process cancelled.', 'info')
            break

        local_path = dir_path / filename
        absolute_file_url = urllib.parse.urljoin(url, 'download?' + file_url)
        
        if should_download(ezshare_instance, local_path, file_ts,
                           getattr(ezshare_instance, '_remote_sizes', {}).get((url, file_url))):
            progress_msg = f'Downloading file "{filename}" {processed_files + 1}/{total_files}'
            ezshare_instance.update_status(progress_msg + (f" ({int((processed_files + 1) / total_files * 100)}%)" if total_files else " (0%)"))
            if download_file(ezshare_instance, absolute_file_url, local_path, file_ts):
                processed_files += 1
                progress_value = (processed_files / total_files) * 100
                ezshare_instance.update_progress(min(max(0, progress_value), 100))
            else:
                ezshare_instance.transfer_failed = True
    return processed_files

def should_download(ezshare_instance, local_path, file_ts, remote_size=None):
    """
    Determine if a file should be downloaded based on its timestamp and existence.

    :param ezshare_instance: Instance of the main application containing settings and states.
    :param local_path: Local file path.
    :param file_ts: Timestamp of the remote file.
    :return: True if the file should be downloaded, False otherwise.
    """
    if local_path.is_file() and remote_size is not None and local_path.stat().st_size != remote_size:
        return True
    return not (local_path.is_file() and not (ezshare_instance.overwrite or local_path.stat().st_mtime < file_ts) and not ezshare_instance.keep_old)

def download_file(ezshare_instance, url, file_path, file_ts=None):
    """
    Download a file from the given URL and save it locally.

    :param ezshare_instance: Instance of the main application containing settings and states.
    :param url: URL of the file to download.
    :param file_path: Local path where the file should be saved.
    :param file_ts: Optional timestamp to set on the downloaded file.
    :return: True if the file was downloaded successfully, False otherwise.
    """
    max_retries = ezshare_instance.retries
    retries = max_retries
    while retries > 0:
        tmp_file_path = None
        cancelled = False
        try:
            response = ezshare_instance.session.get(url, stream=True, timeout=5)
            response.raise_for_status()

            length = response.headers.get('content-length')
            total_size = int(length) if length is not None else None
            received = 0
            with NamedTemporaryFile(delete=False, dir=file_path.parent, prefix='.ezshare-part-') as tmp_file:
                tmp_file_path = pathlib.Path(tmp_file.name)
                for data in response.iter_content(1024):
                    if not ezshare_instance._is_running:
                        logger.info('Cancelling download of %s', str(file_path))
                        cancelled = True
                        break
                    tmp_file.write(data)
                    received += len(data)
                tmp_file.flush()
                os.fsync(tmp_file.fileno())

            if cancelled:
                tmp_file_path.unlink(missing_ok=True)
                return False

            if total_size is not None and received != total_size:
                raise ValueError('Incomplete response body')
            tmp_file_path.replace(file_path)
            tmp_file_path = None
            logger.info('%s written', str(file_path))
            if file_ts:
                os.utime(file_path, (file_ts, file_ts))
            return True  # Successful download
        except Exception as e:
            if tmp_file_path:
                tmp_file_path.unlink(missing_ok=True)
            retries -= 1
            logger.error(f'Error downloading file {file_path}: {e}. Retries left: {retries}')
            if retries == 0:
                return False  # Return False after all retries have been exhausted
            else:
                time.sleep(ezshare_instance.connection_delay)  # Wait before retrying
def check_dirs(ezshare_instance, dirs, url, dir_path, total_files, processed_files, is_running):
    """
    Recursively process each directory in the list.

    :param ezshare_instance: Instance of the main application containing settings and states.
    :param dirs: List of directories to process.
    :param url: URL of the current directory being processed.
    :param dir_path: Local directory path to store files.
    :param total_files: Total number of files expected to be processed.
    :param processed_files: Count of files already processed.
    :param is_running: Function to check if the process should continue running.
    :return: Updated count of processed files.
    """
    for dirname, dir_url in dirs:
        if not is_running():
            ezshare_instance.update_status('Process cancelled.', 'info')
            break

        new_dir_path = dir_path / dirname
        new_dir_path.mkdir(exist_ok=True)
        absolute_dir_url = urllib.parse.urljoin(url, dir_url)
        processed_files = recursive_traversal(ezshare_instance, absolute_dir_url, new_dir_path, total_files, processed_files, is_running)
    return processed_files
