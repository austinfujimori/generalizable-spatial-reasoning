import os
import sys
import threading
import boto3
from botocore.exceptions import ClientError


def upload_file_to_s3(s3_client, file_name, target_file_path=None, bucket_name="playcanvas-public"):
     """
     Upload a file to an S3 bucket with improved progress tracking
     :param file_name: File to upload
     :param bucket_name: Bucket to upload to
     :param s3_client: Boto3 S3 client
     :param target_file_path: S3 object name. If not specified, file_name is used
     :return: URL of the uploaded file if successful, else None
     """

     if target_file_path is None:
          arget_file_path = os.path.basename(file_name)
     
     class ProgressPercentage(object):
          def __init__(self, filename):
               self._filename = filename
               self._size = float(os.path.getsize(filename))
               self._seen_so_far = 0
               self._lock = threading.Lock()

          def __call__(self, bytes_amount):
               # Update the progress bar
               with self._lock:
                    self._seen_so_far += bytes_amount
                    percentage = (self._seen_so_far / self._size) * 100
                    sys.stdout.write(
                         "\rUploading %s  %.2f%%" % (
                              self._filename, percentage))
                    sys.stdout.flush()

     try:
          s3_client.upload_file(
               file_name, bucket_name, target_file_path,
               Callback=ProgressPercentage(file_name)
          )
     except ClientError as e:
          print(f"\nAn error occurred: {e}")
          return None

     # Construct the URL of the uploaded file
     url = f"https://{bucket_name}.s3.amazonaws.com/{target_file_path}"
     print(f"\nUpload complete! File available at: {url}")
     return url


def check_if_s3_object_exists(s3_client, object_key, bucket_name="playcanvas-public"):
     try:
          s3_client.head_object(Bucket=bucket_name, Key=object_key)
          return True
     except ClientError as e:
          # Check if it's a 404 error (i.e., object does not exist)
          if e.response['Error']['Code'] == '404':
               return False
          else:
               raise e