import boto3
import botocore
import jwplatform
import requests
import json
import csv
import xmltodict
import datetime
import calendar
import urllib3

# This function is a proof of concept and should not be used for production
# Never share your API Key or Secret. These can not be regenerated

def lambda_handler(event, context):
    #define S3, SQS & AWS params
    s3 = boto3.resource('s3')
    s3Client = boto3.client('s3')
    bucket_name = event['Records'][0]['s3']['bucket']['name'];
    key = event['Records'][0]['s3']['object']['key'];
    file_path = key.split(".")[0]
    file_type = key.split(".")[1]
    bucket_url = f"https://s3.us-east-2.amazonaws.com/{bucket_name}/"
    
    # SQS Config
    sqs = boto3.client('sqs')
    queue_url = 'https://sqs.us-east-2.amazonaws.com/399317258909/accu-jw-poll'
    
    # Key & secret for JW Platform API calls
    # Configurations
    vkey = ''
    vsecret = ''
    
    # Define JW Player
    
    jwplatform_client = jwplatform.Client(vkey, vsecret)
    
    # By default this means we are only uploading a new file, not updating one
    update_asset = 3
    
    #declare False values for our data and video
    data_file_path = False
    video_file_path = False
    captions_file_path = False

    #define our inner functions for repeated use
    def XMLtoJSON(file):
        with requests.Session() as s:
            download = s.get(file)
            dc = download.content.decode('utf-8')
             
        jsonString = json.dumps(xmltodict.parse(dc, process_namespaces=True))
        return json.loads(jsonString)
        
    def checkForFile(file, bucket):
        # try to hit this the file with a HEAD request
        # should check for any captions or metadata tracks too
        try:
            s3.Object(bucket, file).load()
        except botocore.exceptions.ClientError as e:
            if e.response['Error']['Code'] == "404":
                
                return e.response
                
            else:
                
                return e.response
        else:
            return True
    
    def publicUrl(file):
        
        pub_file = s3Client.generate_presigned_url('get_object', Params = {'Bucket': bucket_name, 'Key': file}, ExpiresIn = 1000)    
        return pub_file
        
    def uploadCaptions(api_response, captions_file_path, label):
        captions_obj = {}
        captions_obj['video_key'] = api_response.get('video',{'key': 'NA'})['key']
        captions_obj['kind'] = "captions"
        captions_obj['label'] = label
        response = jwplatform_client.videos.tracks.create(**captions_obj)
        
        # Construct base url for upload
        upload_url = '{}://{}{}'.format(
            response['link']['protocol'],
            response['link']['address'],
            response['link']['path']
        )
    
        # Query parameters for the upload
        query_parameters = response['link']['query']
        query_parameters['api_format'] = "json"
        
        http = urllib3.PoolManager()

        url = publicUrl(captions_file_path)
        response = http.request('GET', url)
        f = response.data
        
        files = {'file': f}
        r = requests.post(upload_url, params=query_parameters, files=files)
        
        return r    
    
    def getKeyFromHashCode(hash_code):
        search_params = {}
        search_params['search:custom.hash_code'] = hash_code
        get_media_key = jwplatform_client.videos.list(**search_params)
        
        return get_media_key['videos'][0]['key']
        
    def sendSQS(queue_url, media_id):
        response = sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=(
                media_id
            )
        )
        
        return response
    
    #check if the file is an mp4 or not
    if file_type == "mp4":
        
        video_file_path = bucket_url + file_path + ".mp4"
        if checkForFile(file_path + ".xml", bucket_name):
            
            xml_url = publicUrl(file_path + ".xml")
            data_file_path = XMLtoJSON(xml_url)
            data_type = "xml"
            
        else:
            
            #metadata isn't here yet, we abort
            return "No metadata"
        
    else:
        
        # Event file is not an mp4 file, let's see if we have one in the bucket
        if checkForFile(file_path + ".mp4", bucket_name):
            
            video_file_path = bucket_url + file_path + ".mp4"
            
            # Now let's check what file triggered the event
            # If not XML, assumed DFXP and ignore
            if file_type == "xml":
                xml_url = publicUrl(file_path + ".xml")
                data_file_path = XMLtoJSON(xml_url)
                data_type = "xml"
            
            else:
                
                # Bad file type, Abort
                return "DFXP, not xml"
            
        else:
            
            #file isn't here yet, we abort
            return False
    
    if video_file_path and data_file_path:
        
        media_object = {}
        
        if data_type == "xml":
            
            # Parse data from XML
            
            # Set Video Path
            if data_file_path["publisher-upload-manifest"]["asset"][0]["@filename"]:
                video_file = data_file_path["publisher-upload-manifest"]["asset"][0]["@filename"]
                media_object["download_url"] = publicUrl(video_file)
                
            # Get Title of Video
            if data_file_path["publisher-upload-manifest"]["title"]["@name"]:
                media_object["title"] = data_file_path["publisher-upload-manifest"]["title"]["@name"]
            
            # Get Description if one exists
            if data_file_path["publisher-upload-manifest"]["title"]["short-description"]:
                media_object["description"] = data_file_path["publisher-upload-manifest"]["title"]["short-description"]
            
            # Generate Tags
            if data_file_path["publisher-upload-manifest"]["title"]["tag"]:
                media_object["tags"] = ','.join(map(str, data_file_path["publisher-upload-manifest"]["title"]["tag"]))
                
            # Start Date
            if data_file_path["publisher-upload-manifest"]["title"]["@start-date"]:
                date = data_file_path["publisher-upload-manifest"]["title"]["@start-date"]
                date = datetime.datetime.strptime(date, "%m/%d/%Y %H:%M %p")
                
                # +28800 to add 8 hours for UTC offset to EST
                media_object["date"] = calendar.timegm(date.utctimetuple()) + 28800
            
            # End Date
            if data_file_path["publisher-upload-manifest"]["title"]["@end-date"]:
                expire_date = data_file_path["publisher-upload-manifest"]["title"]["@end-date"]
                expire_date = datetime.datetime.strptime(expire_date, "%m/%d/%Y %H:%M %p")
                
                # +28800 to add 8 hours for UTC offset to EST
                media_object["expire_date"] = calendar.timegm(expire_date.utctimetuple()) + 28800
            
            # Get GUID for asset
            if data_file_path["publisher-upload-manifest"]["asset"][0]["@hash-code"]:
                media_object["custom.hash_code"] = data_file_path["publisher-upload-manifest"]["asset"][0]["@hash-code"]
            
            if data_file_path["publisher-upload-manifest"]["asset"][1]["@filename"]:
                captions_file_path = data_file_path["publisher-upload-manifest"]["asset"][1]["@filename"]
                
            # Check if this is an update or a new asset    
            if data_file_path["publisher-upload-manifest"]["reencode-from-new-source"]["@new-source-refid"]:
                
                update_asset = int(data_file_path["publisher-upload-manifest"]["reencode-from-new-source"]["@replace"])
                
        else:
            return "Not valid XML"
            
        # Check to see if this is a new asset, or an update
        
        # 1 = create new 
        if update_asset == 1 or not update_asset:
            
            api_response = jwplatform_client.videos.create(**media_object)
            
            if captions_file_path:
               uploadCaptions(api_response, captions_file_path, "English")
            
            return api_response
            
        # 2 = update            
        elif update_asset and update_asset == 2:
            
            media_object['update_file'] = True
            jw_media_id = getKeyFromHashCode(media_object['custom.hash_code'])
            media_object['video_key'] = jw_media_id
            video_file = data_file_path["publisher-upload-manifest"]["reencode-from-new-source"]["@new-source-refid"]
            media_object['download_url'] = publicUrl(video_file)
            media_object['update_file'] = True
            
            api_response = jwplatform_client.videos.update(**media_object)
            
            if api_response['status'] == "ok":
                sendSQS(queue_url, jw_media_id)
            
        # 3 = update & create new
        else:
            
            api_response = jwplatform_client.videos.create(**media_object)
            
            if captions_file_path:
                uploadCaptions(api_response, captions_file_path, "English")

            video_file = data_file_path["publisher-upload-manifest"]["reencode-from-new-source"]["@new-source-refid"]
            media_object['download_url'] = publicUrl(video_file)
            media_object['update_file'] = True
            jw_media_id = getKeyFromHashCode(media_object['custom.hash_code'])
            media_object['video_key'] = jw_media_id
            
            api_update_response = jwplatform_client.videos.update(**media_object)
            
            if api_update_response['status'] == "ok":
                sendSQS(queue_url, jw_media_id)