import boto3
import botocore
import jwplatform
import json
import requests

# This function is a proof of concept and should not be used for production
# Never share your API Key or Secret. These can not be regenerated

def lambda_handler(event, context):
    #define SQS & AWS params
    sqs = boto3.client('sqs')
    queue_url = 'https://sqs.us-east-2.amazonaws.com/399317258909/accu-jw-poll'
    
    # Key & secret for JW Platform API calls
    # Configurations
    vkey = 'YYYYYYYY'
    vsecret = 'XXXXXXXXXXXXXXXXXXX'
    
    # Define JW Player
    jwplatform_client = jwplatform.Client(vkey, vsecret)
    
    # default new_messages to True so we can start polling
    # set rate limit to 40, don't want to stall any other processes
    new_messages = True
    min_rate_limit = 40

    # Check if there are messages in the response
    while new_messages and min_rate_limit >= 40:
        try:
            # Get a message from the queue, if there is one
            resp = sqs.receive_message(
                QueueUrl=queue_url,
                AttributeNames=['All']
            )
            
            # get the Media Id
            jw_media_id = resp['Messages'][0]['Body']
            sqs_receipt = resp['Messages'][0]['ReceiptHandle']
            
            # Check if status of media is ready & min_rate_limit >= 40
            # if so, make the API call & check to make sure it was successful. Else, exit()
            # if it's successful, delete the msg, log our rate limit, and move on to next msg
            api_response = jwplatform_client.videos.show(video_key=jw_media_id)
            
            if api_response['video']['status'] == "ready" and min_rate_limit >= 40:
                thumb_response = jwplatform_client.videos.thumbnails.update(video_key=jw_media_id,position=3)
                min_rate_limit = thumb_response['rate_limit']['remaining']
                
                if thumb_response['status'] == "ok":
                    sqs.delete_message(
                        QueueUrl=queue_url,
                        ReceiptHandle=sqs_receipt
                    )
            else:
                # If it's not "ready", set min_rate_limit & move on to next msg in queue
                min_rate_limit = thumb_response['rate_limit']['remaining']
            
        except KeyError:
            return 'No more messages on the queue!'
            messages = []
            new_messages = False