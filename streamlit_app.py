from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import streamlit as st
import difflib

# Use session state to store credentials
if 'credentials' not in st.session_state:
    st.session_state.credentials = None

def authenticate_user():
    # Access secrets
    client_config = {
        "web": st.secrets["web"]
    }
    scopes = ['https://www.googleapis.com/auth/youtube.force-ssl']
    flow = InstalledAppFlow.from_client_config(client_config, scopes, redirect_uri='https://youtube-bulk-updater-jocoding.streamlit.app/')
    if 'credentials' not in st.session_state or st.session_state.credentials is None:
        auth_url, _ = flow.authorization_url(prompt='consent')
        st.link_button("Login", auth_url)

    # Handle the response callback
    if st.query_params.get_all("code"):
        if not st.session_state.get('auth_code_processed', False):
            auth_code = st.query_params["code"]
            try:
                flow.fetch_token(code=auth_code)
                st.session_state.credentials = flow.credentials
                st.rerun()
            except Exception as e:
                st.error(f"Error exchanging auth code for tokens: {e}")

def get_authenticated_service():
    if st.session_state.credentials:
        return build('youtube', 'v3', credentials=st.session_state.credentials)
    else:
        return None

def fetch_channel_details(youtube):
    request = youtube.channels().list(
        part="snippet,contentDetails,statistics",
        mine=True
    )
    response = request.execute()
    channel_info = response["items"][0]
    channel_name = channel_info["snippet"]["title"]
    subscribers_count = channel_info["statistics"]["subscriberCount"]
    total_videos = channel_info["statistics"]["videoCount"]
    profile_image_url = channel_info["snippet"]["thumbnails"]["default"]["url"]
    return channel_name, subscribers_count, total_videos, profile_image_url

def fetch_user_playlists(youtube):
    """
    Fetches the user's YouTube playlists and returns a list of tuples containing the playlist's title and ID.
    """
    playlists = []
    next_page_token = None

    while True:
        response = youtube.playlists().list(
            part="snippet",
            mine=True,
            maxResults=50,
            pageToken=next_page_token
        ).execute()

        for item in response["items"]:
            playlists.append((item["snippet"]["title"], item["id"]))

        next_page_token = response.get('nextPageToken')
        if not next_page_token:
            break

    return playlists

def fetch_video_ids_from_playlist_or_channel(youtube, playlist_id=None):
    """
    Fetches video IDs from a specific playlist if a playlist ID is provided.
    If no playlist ID is provided, fetches all video IDs from the user's channel.
    """
    video_ids = []
    request = None

    if playlist_id:
        # Fetch from specific playlist
        request = youtube.playlistItems().list(part="snippet", playlistId=playlist_id, maxResults=50)
    else:
        # Fetch from user's upload playlist (default behavior)
        channels_response = youtube.channels().list(mine=True, part='contentDetails').execute()
        uploads_playlist_id = channels_response['items'][0]['contentDetails']['relatedPlaylists']['uploads']
        request = youtube.playlistItems().list(part="snippet", playlistId=uploads_playlist_id, maxResults=50)
    
    while request:
        response = request.execute()
        video_ids.extend([item['snippet']['resourceId']['videoId'] for item in response['items']])
        request = youtube.playlistItems().list_next(request, response)
    
    return video_ids

def fetch_videos_from_playlist(youtube, playlist_id):
    """
    Fetches video IDs and other details from a specific playlist.
    """
    video_details = []
    request = youtube.playlistItems().list(part="snippet", playlistId=playlist_id, maxResults=50)
    while request:
        response = request.execute()
        for item in response["items"]:
            video_id = item["snippet"]["resourceId"]["videoId"]
            title = item["snippet"]["title"]
            description = item["snippet"]["description"]
            publishedAt = item["snippet"]["publishedAt"]
            video_details.append({"video_id": video_id, "title": title, "description": description, "publishedAt": publishedAt})
        request = youtube.playlistItems().list_next(request, response)
    return video_details

def preview_video_descriptions_with_replacements(youtube, video_ids, replacements):
    # Function to preview changes without applying them
    previews = []  # Store previews here
    for video_id in video_ids:
        try:
            video_request = youtube.videos().list(part="snippet", id=video_id)
            video_response = video_request.execute()
            video_snippet = video_response["items"][0]["snippet"]
            title = video_snippet["title"]
            publishedAt = video_snippet["publishedAt"]
            original_description = video_snippet["description"]
            
            # Apply replacements to generate a new description
            new_description = original_description
            for old_word, new_word in replacements.items():
                new_description = new_description.replace(old_word, new_word)
            
            # If the description changes, add it to the previews
            if new_description != original_description:
                previews.append({
                    "video_id": video_id,
                    "title": title,
                    "publishedAt": publishedAt,
                    "original_description": original_description,
                    "new_description": new_description,
                    "video_url": f"https://youtu.be/{video_id}"
                })
        except Exception as e:
            st.error(f"Failed to preview video {video_id}: {e}")
    
    return previews

def update_video_descriptions_with_replacements(youtube, video_ids, replacements):
    updated_count = 0  # Initialize counter
    errors = []  # List to store error messages

    for video_id in video_ids:
        try:
            # Fetch current video details
            video_request = youtube.videos().list(part="snippet", id=video_id)
            video_response = video_request.execute()
            video_snippet = video_response["items"][0]["snippet"]
            original_description = video_snippet["description"]

            # Replace words in the description
            new_description = original_description
            for old_word, new_word in replacements.items():
                new_description = new_description.replace(old_word, new_word)
            
            # Update the video description if it has changed
            if new_description != original_description:
                video_snippet["description"] = new_description
                update_request = youtube.videos().update(
                    part="snippet",
                    body={"id": video_id, "snippet": video_snippet}
                )
                update_request.execute()
                updated_count += 1  # Increment counter when a video is updated
        except Exception as e:
            errors.append(f"Failed to update video {video_id}: {e}")
    
    return updated_count, errors

def generate_html_diff_view(original_text, new_text):
    """
    Generates an HTML diff view to visualize changes between original and new text.
    This version filters out diff metadata to improve readability.
    """
    diff = difflib.ndiff(original_text.splitlines(keepends=True), new_text.splitlines(keepends=True))
    html_diff = ''
    for line in diff:
        # Skip diff metadata lines that start with '?'
        if line.startswith('?'):
            continue
        if line.startswith('- '):
            # For deleted lines, wrap with <del> and replace newlines with <br> for HTML rendering
            html_diff += f"<del style='background-color:#fbb6ce;'>{line[2:].rstrip()}</del><br>"
        elif line.startswith('+ '):
            # For inserted lines, wrap with <ins> and replace newlines with <br> for HTML rendering
            html_diff += f"<ins style='background-color:#d3f9d8;'>{line[2:].rstrip()}</ins><br>"
        else:
            # For unchanged lines, directly append them with a <br> at the end for line breaks
            html_diff += f"{line[2:].rstrip()}<br>"
    return html_diff

def main():
    st.title("YouTube Bulk Updater - 유튜브 벌크 업데이터")
    st.markdown("by 유튜버 [조코딩 JoCoding](https://www.youtube.com/channel/UCQNE2JmbasNYbjGAcuBiRRg)")
    st.divider()

    if not st.session_state.credentials:
        authenticate_user()
    
    youtube = get_authenticated_service()
    if youtube:
        channel_name, subscribers_count, total_videos, profile_image_url = fetch_channel_details(youtube)
        with st.container():
            col1, col2 = st.columns([1, 3])
            with col1:
                profile_image_html = f"""
                <style>
                    .img-container {{
                        display: flex;
                        justify-content: center;
                        align-items: center;
                    }}
                    img {{
                        border-radius: 50%;
                        width: 100px;
                        height: 100px;
                        box-shadow: 0 4px 8px 0 rgba(0, 0, 0, 0.2), 0 6px 20px 0 rgba(0, 0, 0, 0.19);
                    }}
                </style>
                <div class="img-container">
                    <img src='{profile_image_url}' alt='Channel profile image'>
                </div>
                """
                st.markdown(profile_image_html, unsafe_allow_html=True)
            with col2:
                st.markdown(f"""
                <style>
                    .channel-info {{
                        font-family: 'Arial', sans-serif;
                    }}
                </style>
                <div class="channel-info">
                    <h4>{channel_name}</h4>
                    <p><strong>Subscribers:</strong> {subscribers_count}</p>
                    <p><strong>Total Video Count:</strong> {total_videos}</p>
                </div>
                """, unsafe_allow_html=True)
        
        # Fetch and display user playlists for selection
        user_playlists = fetch_user_playlists(youtube)
        playlist_titles = [playlist[0] for playlist in user_playlists]
        playlist_ids = [playlist[1] for playlist in user_playlists]

        # Include an option for "All Videos"
        playlist_titles.insert(0, "All Videos")
        playlist_ids.insert(0, None)

        selected_playlist_title = st.selectbox("Select a playlist:", options=playlist_titles)
        selected_index = playlist_titles.index(selected_playlist_title)
        selected_playlist_id = playlist_ids[selected_index]

        # Fetch Video IDs from either specified playlist or user's channel
        video_ids = fetch_video_ids_from_playlist_or_channel(youtube, selected_playlist_id)

        st.divider()
        st.header('Fix description', divider='rainbow')

        oldText = st.text_area("Find (text to be replaced):", height=100)
        newText = st.text_area("Replace with:", height=100)
        
        # Adjustments here: Allow replacements with an empty string if 'Replace with:' is empty
        replacements = {oldText: newText} if oldText else {}

        if 'preview_data' not in st.session_state:
            st.session_state.preview_data = []

        if st.button("Preview Changes"):
            if oldText:  # newText can be empty, allowing erasure of found text
                st.session_state.preview_data = preview_video_descriptions_with_replacements(youtube, video_ids, replacements)
                total_changes = len(st.session_state.preview_data)
                if total_changes == 0:
                    st.warning("No changes detected with the provided terms.")
                else:
                    st.success(f"Total changes detected: {total_changes}")
                    for item in st.session_state.preview_data[:5]:  # Show previews for up to 5 changes
                        expander_label = f"***{item['title']}*** {item['publishedAt'].split()[0][:10]}"
                        with st.expander(expander_label):
                            html_diff = generate_html_diff_view(item['original_description'], item['new_description'])
                            st.markdown(html_diff, unsafe_allow_html=True)
            else:
                st.error("Please enter a term to find.")

        if st.button("Confirm and Update"):
            if st.session_state.preview_data:
                updated_count, errors = update_video_descriptions_with_replacements(youtube, [item['video_id'] for item in st.session_state.preview_data], replacements)
                if errors:
                    for error in errors:
                        st.error(error)
                st.success(f"Update successful for {updated_count} videos.")
                st.session_state.preview_data = []  # Clear the previews after updating
            else:
                st.error("No changes to apply. Please preview changes before confirming.")

        # Advertising banner
        st.markdown("""
        <hr style="border:1px solid #ccc">
        <p style="text-align:center;">
            AD) 영상 자막/번역/더빙이 필요하다면? <a href="https://jocasso.codemafia.io/subtitle" target="_blank">Jocasso AI</a>
        </p>
        <hr style="border:1px solid #ccc">
        """, unsafe_allow_html=True)

main()