import os
import json
import googleapiclient.discovery
import googleapiclient.errors

def get_channel_id_from_handle(youtube, handle):
    # If it's already a UC... ID, just return it
    if handle.startswith("UC"):
        return handle
    
    # Remove @ if present
    query = handle.replace("@", "")
    
    search_response = youtube.search().list(
        q=query,
        type="channel",
        part="id",
        maxResults=1
    ).execute()

    if not search_response.get("items"):
        return None
    
    return search_response["items"][0]["id"]["channelId"]

def fetch_channel_videos(api_key, handle_or_id):
    try:
        youtube = googleapiclient.discovery.build("youtube", "v3", developerKey=api_key)

        # Resolve handle to ID if necessary
        channel_id = get_channel_id_from_handle(youtube, handle_or_id)
        
        if not channel_id:
            print(f"Error: Could not find channel for '{handle_or_id}'")
            return []

        print(f"Found Channel ID: {channel_id}")

        # 1. Get the 'uploads' playlist ID
        channel_response = youtube.channels().list(
            part="contentDetails",
            id=channel_id
        ).execute()

        if "items" not in channel_response or not channel_response["items"]:
            print(f"Error: No content found for Channel ID '{channel_id}'")
            return []

        uploads_playlist_id = channel_response["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

        # 2. Get latest videos
        playlist_response = youtube.playlistItems().list(
            part="snippet",
            playlistId=uploads_playlist_id,
            maxResults=10
        ).execute()

        videos = []
        for item in playlist_response["items"]:
            snippet = item["snippet"]
            video_data = {
                "title": snippet["title"],
                "id": snippet["resourceId"]["videoId"],
                "thumbnail": snippet["thumbnails"].get("maxres", snippet["thumbnails"].get("high", {}))["url"],
                "creator": snippet["channelTitle"]
            }
            videos.append(video_data)
        
        return videos

    except googleapiclient.errors.HttpError as e:
        print(f"YouTube API Error: {e.reason}")
        return []
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return []

def update_website_data(videos):
    with open("videos.json", "w") as f:
        json.dump(videos, f, indent=4)
    print(f"✅ Successfully updated videos.json with {len(videos)} videos!")

if __name__ == "__main__":
    # --- YOUR CONFIGURATION ---
    API_KEY = "AIzaSyAkegt5QFnP_7pWolYrwPe0OyjFnysNps8"
    
    # CHANGE THIS: Put your client's YouTube Handle or Name here
    # Example: "@MrBeast", "@YouTubeCreators", or "@YourClient"
    TARGET = "@MrBeast" 
    
    print(f"🚀 Starting automation for: {TARGET}...")
    video_list = fetch_channel_videos(API_KEY, TARGET)
    
    if video_list:
        update_website_data(video_list)
    else:
        print("❌ Failed to fetch videos. Try a different channel handle.")
