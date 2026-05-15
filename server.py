"""
YouTube AI Analyzer - Backend Server
Designed for Railway deployment
"""

import os
import re
import json
import urllib.request
import urllib.error
import requests
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
    Get YouTube transcript using multiple methods.
    Railway allows connections to YouTube unlike Render.
    """
    
    # ============================================
    #  METHOD 1: Direct YouTube subtitle download
    # ============================================
    try:
        for lang in ['en', 'en-US', 'en-GB']:
            try:
                url = f"https://www.youtube.com/api/timedtext?v={video_id}&lang={lang}"
                req = urllib.request.Request(url, headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
                    'Accept': '*/*'
                })
                with urllib.request.urlopen(req, timeout=10) as resp:
                    content = resp.read()
                    if content and len(content) > 100:
                        decoded = content.decode('utf-8', errors='ignore')
                        if '<?xml' in decoded or '<tt' in decoded or '<text' in decoded:
                            # Parse TTML/XML format
                            texts = re.findall(r'<text[^>]*>([^<]+)</text>', decoded)
                            if texts:
                                lines = []
                                for text in texts:
                                    text = text.replace('&amp;', '&').replace('&quot;', '"').replace('&#39;', "'").replace('&lt;', '<').replace('&gt;', '>')
                                    if text.strip():
                                        lines.append(text.strip())
                                if lines:
                                    return '\n'.join(lines)
                        return decoded
            except Exception as e:
                print(f"Lang {lang} failed: {e}")
                continue
    except Exception as e:
        print(f"Method 1 failed: {e}")
    
    # ============================================
    #  METHOD 2: youtube-transcript-api
    # ============================================
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound
        
        # Try list_transcripts first
        try:
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
            
            for transcript in transcript_list:
                if transcript.language_code.startswith('en'):
                    data = transcript.fetch()
                    lines = []
                    for entry in data:
                        mins = int(entry.start) // 60
                        secs = int(entry.start) % 60
                        text = entry.text.replace('\n', ' ').strip()
                        if text:
                            lines.append(f"[{mins:02d}:{secs:02d}] {text}")
                    if lines:
                        return '\n'.join(lines)
        except:
            pass
        
        # Try legacy get_transcript
        try:
            transcript = YouTubeTranscriptApi.get_transcript(video_id)
            lines = []
            for entry in transcript:
                mins = int(entry['start']) // 60
                secs = int(entry['start']) % 60
                text = entry['text'].replace('\n', ' ').strip()
                if text:
                    lines.append(f"[{mins:02d}:{secs:02d}] {text}")
            if lines:
                return '\n'.join(lines)
        except:
            pass
            
    except Exception as e:
        print(f"Method 2 error: {type(e).__name__}: {e}")
    
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
    """Get transcript from YouTube"""
    video_id = request.args.get('video_id', '')
    video_id = extract_video_id(video_id)
    if not video_id:
        return jsonify({'error': 'Invalid video ID'}), 400

    transcript = get_transcript(video_id)
    if transcript:
        return jsonify({
            'success': True, 
            'transcript': transcript,
            'length': len(transcript)
        })

    return jsonify({
        'success': False, 
        'error': 'No transcript available for this video. This video may not have captions.'
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

    has_real_transcript = bool(transcript and len(transcript) > 50)

    prompts = {
        'transcript': f"""You are a YouTube content analyst.

VIDEO TITLE: {title}
CHANNEL: {channel}
VIEWS: {views}
HAS REAL TRANSCRIPT: {'Yes' if has_real_transcript else 'No'}
{'-' * 40}
VIDEO TRANSCRIPT:
{transcript if transcript else 'NO TRANSCRIPT - Analysis based on title: "' + title + '"'}
{'-' * 40}

RULES:
- If NO transcript: Be honest about it
- NEVER use placeholder text like "topic 1", "point 1"
- Return valid JSON only

JSON:
{{
    "fullScript": "Real content or honest message",
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
{transcript[:2000] if transcript else 'No transcript. Based on title only.'}
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

# ============================================
#  START SERVER
# ============================================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
