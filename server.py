"""
YouTube AI Analyzer - Backend Server
"""

import os
import re
import json
from flask import Flask, request, jsonify
from flask_cors import CORS
from youtube_transcript_api import YouTubeTranscriptApi
from openai import OpenAI
import urllib.request
import urllib.error

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
    """Get video info from YouTube oEmbed (no API key needed)"""
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
    except Exception as e:
        print(f"oEmbed error: {e}")
        return None

def get_video_stats(video_id):
    """Get video stats from YouTube Data API v3"""
    if not GOOGLE_API_KEY:
        print("No Google API Key - stats will be 0")
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
            'favoriteCount': stats.get('favoriteCount', '0'),
            'title': snippet.get('title', ''),
            'channel': snippet.get('channelTitle', ''),
            'publishedAt': snippet.get('publishedAt', ''),
            'description': snippet.get('description', '')
        }
    except urllib.error.HTTPError as e:
        print(f"Google API HTTP error: {e.code} - {e.read()}")
        return None
    except Exception as e:
        print(f"Google API error: {e}")
        return None

def get_transcript(video_id):
    """Get YouTube transcript using youtube-transcript-api"""
    try:
        ytt = YouTubeTranscriptApi()
        # Try to get transcript in multiple languages
        try:
            # Try English first
            transcript_list = ytt.fetch(video_id, languages=['en'])
        except:
            try:
                # Try any available language
                transcript_list = ytt.fetch(video_id)
            except:
                # Try with proxy
                transcript_list = ytt.fetch(video_id, languages=['en', 'ar', 'es', 'de', 'fr', 'pt', 'it', 'ru', 'ja', 'ko', 'zh-Hans', 'zh-Hant'])
        
        lines = []
        for entry in transcript_list:
            mins = int(entry.start) // 60
            secs = int(entry.start) % 60
            text = entry.text.replace('\n', ' ').replace('&amp;', '&').replace('&quot;', '"').replace('&#39;', "'").strip()
            if text:
                lines.append(f"[{mins:02d}:{secs:02d}] {text}")
        
        return '\n'.join(lines) if lines else None
    except Exception as e:
        print(f"Transcript fetch error: {e}")
        return None

# ============================================
#  ROUTES
# ============================================
@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        'status': 'ok',
        'ai': bool(client),
        'google': bool(GOOGLE_API_KEY),
        'google_key': GOOGLE_API_KEY[:10] + '...' if GOOGLE_API_KEY else None
    })

@app.route('/video', methods=['GET'])
def video():
    """Get video info and stats"""
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
        # Fill with zeros if no Google API
        info['viewCount'] = '0'
        info['likeCount'] = '0'
        info['commentCount'] = '0'

    return jsonify({'success': True, 'video': info, 'hasStats': bool(stats)})

@app.route('/transcript', methods=['GET'])
def transcript():
    video_id = request.args.get('video_id', '')
    video_id = extract_video_id(video_id)
    if not video_id:
        return jsonify({'error': 'Invalid video ID'}), 400

    transcript = get_transcript(video_id)
    if transcript:
        return jsonify({'success': True, 'transcript': transcript})

    return jsonify({'error': 'No transcript available for this video', 'success': False}), 404

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

    # Check if we have real transcript
    has_real_transcript = bool(transcript and len(transcript) > 50 and '[' not in transcript[:100])

    # ============================================
    #  PROMPTS - ENGLISH
    # ============================================
    prompts = {
        'transcript': f"""You are a YouTube content analyst. Analyze this video using REAL transcript if available.

VIDEO TITLE: {title}
CHANNEL: {channel}
VIEWS: {views}
HAS REAL TRANSCRIPT: {'Yes' if has_real_transcript else 'No'}
{'-' * 40}
VIDEO TRANSCRIPT:
{transcript if transcript else 'NO TRANSCRIPT AVAILABLE - Must say "No transcript available for this video." Do NOT generate fake transcript. Do NOT guess what the video says. Be honest.'}
{'-' * 40}

IMPORTANT RULES:
- If NO transcript available: Write "No transcript available for this video. The analysis is based on the title only: '{title}'" in every field. Do NOT make up content.
- If transcript IS available: Analyze the REAL transcript content.
- NEVER use placeholder text like "topic 1", "point 1", "hook 1"
- Write in English. Return valid JSON only.

JSON format:
{{
    "fullScript": "REAL transcript text with timestamps. If no transcript, write honest message.",
    "mainTopics": ["Real topic 1", "Real topic 2", "Real topic 3"],
    "keyPoints": ["Real key point 1", "Real key point 2", "Real key point 3", "Real key point 4"],
    "hookUsed": "Real hook description from actual content"
}}

JSON ONLY. No text before or after.""",

        'hook': f"""You are a YouTube hook expert. Analyze this video:

VIDEO TITLE: {title}
CHANNEL: {channel}
VIEWS: {views}
{'-' * 40}
VIDEO CONTENT:
{transcript[:2000] if transcript else 'No transcript available. Analyze based on title only: ' + title}
{'-' * 40}

Generate REAL insights. NEVER use placeholder text.
If no transcript: say "No transcript available" honestly.
Write in English. Return valid JSON:

{{
    "hookAnalysis": "Detailed real analysis of the opening",
    "whyViral": ["Real reason 1", "Real reason 2", "Real reason 3", "Real reason 4", "Real reason 5"],
    "suggestedHooks": ["Hook 1", "Hook 2", "Hook 3", "Hook 4", "Hook 5"]
}}

JSON ONLY.""",

        'script': f"""You are a YouTube script writer. Create a similar script:

TITLE: {title}
CHANNEL: {channel}
{'-' * 40}
VIDEO CONTENT:
{transcript[:2000] if transcript else 'No transcript. Be honest: say no transcript available.'}
{'-' * 40}

Generate REAL script based on actual video content.
If no transcript: honestly say "No transcript available".
Write in English. Return JSON:

{{
    "newHook": "Real hook - exact first 5 seconds",
    "newScript": "Real script with timing",
    "keyMoments": ["Moment 1", "Moment 2", "Moment 3", "Moment 4"]
}}

JSON ONLY.""",

        'titles': f"""You are a YouTube SEO expert. Generate 10 click-worthy titles:

VIDEO TITLE: {title}
CHANNEL: {channel}
VIEWS: {views}
{'-' * 40}
CONTENT:
{transcript[:1000] if transcript else 'No transcript - use creativity based on title'}
{'-' * 40}

Requirements:
- Each title under 60 characters
- Different from original
- Click-worthy
- Real titles, not placeholders

Return JSON array:
["Title 1", "Title 2", "Title 3", "Title 4", "Title 5", "Title 6", "Title 7", "Title 8", "Title 9", "Title 10"]

JSON ONLY.""",

        'desc': f"""You are a YouTube description writer. Create SEO description:

TITLE: {title}
CHANNEL: {channel}
{'-' * 40}
CONTENT:
{transcript[:1000] if transcript else 'No transcript'}
{'-' * 40}

Write in English. Return JSON:
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
