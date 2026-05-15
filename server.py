"""
YouTube AI Analyzer - Backend Server
"""

import os
import re
import json
import urllib.request
import urllib.error
from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI

app = Flask(__name__)
CORS(app)

OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY', '')

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# ============================================
#  HELPERS
# ============================================
def extract_video_id(url_or_id):
    patterns = [
        r'(?:v=|youtu\.be\/|embed\/|shorts\/)([a-zA-Z0-9_-]{11})',
        r'^([a-zA-Z0-9_-]{11})$'
    ]
    for p in patterns:
        m = re.search(p, str(url_or_id))
        if m:
            return m.group(1)
    return None

def ask_ai(prompt, system=None):
    if not client:
        return None
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    try:
        resp = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=messages,
            temperature=0.7,
            max_tokens=2500
        )
        return resp.choices[0].message.content
    except Exception as e:
        return f"Error: {str(e)}"

def get_youtube_data(video_id):
    try:
        url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        return {
            'title': data.get('title', ''),
            'author': data.get('author_name', ''),
            'thumbnail': data.get('thumbnail_url', '')
        }
    except:
        return None

def get_video_stats(video_id):
    if not GOOGLE_API_KEY:
        return None
    try:
        url = f"https://www.googleapis.com/youtube/v3/videos?part=statistics,snippet&id={video_id}&key={GOOGLE_API_KEY}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        if not data.get('items'):
            return None
        item = data['items'][0]
        stats = item.get('statistics', {})
        snippet = item.get('snippet', {})
        return {
            'viewCount': stats.get('viewCount', '0'),
            'likeCount': stats.get('likeCount', '0'),
            'commentCount': stats.get('commentCount', '0'),
            'title': snippet.get('title', ''),
            'channel': snippet.get('channelTitle', '')
        }
    except:
        return None

def get_transcript(video_id):
    """
    Get YouTube transcript - REAL transcript from YouTube.
    Tries multiple methods to get captions including auto-generated.
    """
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        from youtube_transcript_api._errors import (
            TranscriptsDisabled, NoTranscriptFound, 
            VideoUnavailable, AgeRestricted, ProxyError
        )
        
        transcript = None
        
        # Method 1: Try the standard way (preferred for auto-captions)
        try:
            # Get all available transcripts
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
            
            # Find the best transcript: prefer English, including auto-generated
            try:
                # Try to find English transcript first (including auto-generated)
                transcript = transcript_list.find_transcript(['en']).fetch()
            except NoTranscriptFound:
                # Try any English variant
                for code in ['en-US', 'en-GB', 'en-AU']:
                    try:
                        transcript = transcript_list.find_transcript([code]).fetch()
                        break
                    except:
                        continue
            except:
                pass
            
            # If still no transcript, try the first available one
            if not transcript or (transcript and len(transcript) == 0):
                for ts in transcript_list:
                    try:
                        if ts.language_code.startswith('en'):
                            transcript = ts.fetch()
                            break
                    except:
                        continue
            
            if transcript:
                lines = []
                for entry in transcript:
                    mins = int(entry.start) // 60
                    secs = int(entry.start) % 60
                    text = entry.text.replace('\n', ' ').replace('&amp;', '&').replace('&quot;', '"').replace('&#39;', "'").replace('<[^>]+>', '').strip()
                    if text and len(text) > 1:
                        lines.append(f"[{mins:02d}:{secs:02d}] {text}")
                if lines:
                    return '\n'.join(lines)
                    
        except (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable, AgeRestricted, ProxyError) as e:
            print(f"YouTube API method 1 blocked: {type(e).__name__}")
        except Exception as e:
            print(f"YouTube API method 1 error: {type(e).__name__}: {e}")
        
        # Method 2: Try with get_transcript (legacy method)
        try:
            raw = YouTubeTranscriptApi.get_transcript(video_id)
            lines = []
            for entry in raw:
                mins = int(entry['start']) // 60
                secs = int(entry['start']) % 60
                text = entry['text'].replace('\n', ' ').strip()
                if text:
                    lines.append(f"[{mins:02d}:{secs:02d}] {text}")
            if lines:
                return '\n'.join(lines)
        except Exception as e:
            print(f"YouTube API method 2 error: {type(e).__name__}: {e}")
        
        # Method 3: Try with proxy (sometimes helps)
        try:
            raw = YouTubeTranscriptApi.get_transcript(
                video_id, 
                languages=['en', 'en-US', 'en-GB']
            )
            lines = []
            for entry in raw:
                mins = int(entry['start']) // 60
                secs = int(entry['start']) % 60
                text = entry['text'].replace('\n', ' ').strip()
                if text:
                    lines.append(f"[{mins:02d}:{secs:02d}] {text}")
            if lines:
                return '\n'.join(lines)
        except Exception as e:
            print(f"YouTube API method 3 error: {type(e).__name__}: {e}")
        
        return None
        
    except ImportError:
        print("youtube-transcript-api not installed")
        return None
    except Exception as e:
        print(f"Transcript error: {type(e).__name__}: {e}")
        return None

# ============================================
#  ROUTES
# ============================================
@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        'status': 'ok',
        'ai': bool(client),
        'google': bool(GOOGLE_API_KEY)
    })

@app.route('/video', methods=['GET'])
def video():
    video_id = request.args.get('video_id', '')
    video_id = extract_video_id(video_id)
    if not video_id:
        return jsonify({'error': 'Invalid video ID'}), 400

    info = get_youtube_data(video_id)
    if not info:
        return jsonify({'error': 'Video not found'}), 404

    stats = get_video_stats(video_id)
    if stats:
        info.update(stats)
    else:
        info['viewCount'] = '0'
        info['likeCount'] = '0'
        info['commentCount'] = '0'

    return jsonify({'success': True, 'video': info, 'hasStats': bool(stats)})

@app.route('/transcript', methods=['GET'])
def transcript():
    """Get REAL transcript from YouTube (no AI)"""
    video_id = request.args.get('video_id', '')
    video_id = extract_video_id(video_id)
    if not video_id:
        return jsonify({'error': 'Invalid video ID'}), 400

    transcript = get_transcript(video_id)
    if transcript:
        return jsonify({
            'success': True, 
            'transcript': transcript,
            'hasRealTranscript': True
        })

    return jsonify({
        'success': False, 
        'error': 'No transcript available for this video',
        'hasRealTranscript': False
    }), 404

@app.route('/analyze', methods=['POST'])
def analyze():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    tool = data.get('tool', '')
    title = data.get('title', '') or data.get('video_title', '')
    channel = data.get('channel', '') or data.get('video_channel', '')
    views = data.get('views', 0) or data.get('video_views', 0)
    transcript = data.get('transcript', '')[:4000]
    video_id = data.get('video_id', '')

    has_real_transcript = bool(transcript and len(transcript) > 50)

    prompts = {
        'transcript': f"""You are a YouTube content analyst.

VIDEO TITLE: {title}
CHANNEL: {channel}
VIEWS: {views}
HAS REAL TRANSCRIPT: {'Yes' if has_real_transcript else 'No'}
{'-' * 40}
VIDEO TRANSCRIPT:
{transcript if transcript else 'NO TRANSCRIPT - Say "No transcript available" in every field.'}
{'-' * 40}

RULES:
- If NO transcript: Say "No transcript available" in every field honestly
- NEVER use placeholder text like "topic 1", "point 1"
- Analyze REAL content only
- Return valid JSON only

JSON:
{{
    "fullScript": "Real content or honest message about no transcript",
    "mainTopics": ["Topic 1", "Topic 2", "Topic 3"],
    "keyPoints": ["Point 1", "Point 2", "Point 3", "Point 4"],
    "hookUsed": "Description"
}}

JSON ONLY.""",

        'hook': f"""You are a YouTube hook expert.

TITLE: {title}
CHANNEL: {channel}
VIEWS: {views}
CONTENT:
{transcript[:2000] if transcript else 'No transcript available. Based on title only.'}
{'-' * 40}

Return JSON:
{{
    "hookAnalysis": "Real analysis",
    "whyViral": ["Reason 1", "Reason 2", "Reason 3", "Reason 4", "Reason 5"],
    "suggestedHooks": ["Hook 1", "Hook 2", "Hook 3", "Hook 4", "Hook 5"]
}}

JSON ONLY.""",

        'script': f"""You are a YouTube script writer.

TITLE: {title}
CHANNEL: {channel}
CONTENT:
{transcript[:2000] if transcript else 'No transcript'}
{'-' * 40}

Return JSON:
{{
    "newHook": "Real hook",
    "newScript": "Real script with timing",
    "keyMoments": ["Moment 1", "Moment 2", "Moment 3", "Moment 4"]
}}

JSON ONLY.""",

        'titles': f"""You are a YouTube SEO expert.

TITLE: {title}
CHANNEL: {channel}
VIEWS: {views}

Return JSON array of 10 strings:
["Title 1", "Title 2", "Title 3", "Title 4", "Title 5", "Title 6", "Title 7", "Title 8", "Title 9", "Title 10"]

JSON ONLY.""",

        'desc': f"""You are a YouTube description writer.

TITLE: {title}
CHANNEL: {channel}

Return JSON:
{{
    "description": "Real description 150-250 words",
    "hashtags": ["#tag1", "#tag2", "#tag3", "#tag4", "#tag5", "#tag6"]
}}

JSON ONLY."""
    }

    if tool not in prompts:
        return jsonify({'error': 'Invalid tool'}), 400

    if not client:
        return jsonify({'error': 'OpenAI API not configured'}), 500

    result = ask_ai(prompts[tool])
    if not result or result.startswith('Error:'):
        return jsonify({'error': result or 'AI request failed'}), 500

    try:
        clean = re.sub(r'```json\s*', '', result, flags=re.IGNORECASE)
        clean = re.sub(r'```\s*', '', clean)
        parsed = json.loads(clean.strip())
        return jsonify({'success': True, 'result': parsed})
    except:
        return jsonify({'success': True, 'result': result})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
