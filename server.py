"""
YouTube AI Analyzer - Backend Server
Flask + YouTube Transcript API + OpenAI
"""

import os
import re
import json
from flask import Flask, request, jsonify
from flask_cors import CORS
from youtube_transcript_api import YouTubeTranscriptApi
from openai import OpenAI

app = Flask(__name__)
CORS(app)

# ============================================
#  CONFIGURATION
# ============================================
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY', '')

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
ytt = YouTubeTranscriptApi()

# ============================================
#  HELPERS
# ============================================
def extract_video_id(url_or_id):
    """Extract video ID from URL or return if already ID"""
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
    """Call OpenAI API with prompt"""
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
            max_tokens=3500
        )
        return resp.choices[0].message.content
    except Exception as e:
        return f"Error: {e}"

def parse_transcript_xml(xml_text):
    """Parse YouTube transcript XML format"""
    texts = re.findall(r'<text[^>]*>([^<]+)</text>', xml_text)
    starts = re.findall(r'start="([\d.]+)"', xml_text)
    result = []
    for i, text in enumerate(texts):
        text = text.strip().replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
        if text:
            start = float(starts[i]) if i < len(starts) else 0
            mins = int(start) // 60
            secs = int(start) % 60
            result.append(f"[{mins:02d}:{secs:02d}] {text}")
    return '\n'.join(result)

# ============================================
#  ROUTES
# ============================================
@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        'status': 'ok',
        'ai': bool(client),
        'google': bool(GOOGLE_API_KEY)
    })

@app.route('/stats', methods=['GET'])
def stats():
    """Get video statistics via YouTube API"""
    video_id = request.args.get('video_id', '')
    video_id = extract_video_id(video_id)
    if not video_id:
        return jsonify({'error': 'Invalid video ID'}), 400

    if GOOGLE_API_KEY:
        try:
            import urllib.request
            url = f"https://www.googleapis.com/youtube/v3/videos?part=statistics&id={video_id}&key={GOOGLE_API_KEY}"
            data = json.loads(urllib.request.urlopen(url).read())
            if data.get('items'):
                s = data['items'][0]['statistics']
                return jsonify({
                    'success': True,
                    'stats': {
                        'viewCount': s.get('viewCount', '0'),
                        'likeCount': s.get('likeCount', '0'),
                        'commentCount': s.get('commentCount', '0')
                    }
                })
        except:
            pass

    return jsonify({'success': True, 'stats': {'viewCount': '0', 'likeCount': '0', 'commentCount': '0'}})

@app.route('/transcript', methods=['GET'])
def transcript():
    """Get YouTube video transcript"""
    video_id = request.args.get('video_id', '')
    video_id = extract_video_id(video_id)
    if not video_id:
        return jsonify({'error': 'Invalid video ID'}), 400

    try:
        transcript_list = ytt.fetch(video_id, languages=['en', 'ar', 'es', 'de', 'fr', 'pt', 'it', 'ru', 'zh'])
        lines = []
        for entry in transcript_list:
            mins = int(entry.start) // 60
            secs = int(entry.start) % 60
            text = entry.text.replace('\n', ' ').strip()
            if text:
                lines.append(f"[{mins:02d}:{secs:02d}] {text}")
        if lines:
            return jsonify({'success': True, 'transcript': '\n'.join(lines)})
        return jsonify({'error': 'No transcript available'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/analyze', methods=['POST'])
def analyze():
    """Main AI analysis endpoint"""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    tool = data.get('tool', '')
    title = data.get('title', '')
    channel = data.get('channel', '')
    views = data.get('views', 0)
    engagement = data.get('engagement', 0)
    transcript = data.get('transcript', '')[:4000]
    trans_preview = transcript[:2000] if transcript else ''

    prompts = {
        'transcript': f"""You are a professional YouTube content analyst. Analyze this video and return JSON:

Title: {title}
Channel: {channel}
Views: {views}
---
{transcript and f'Video Transcript:\n{transcript}\n---\n' or ''}
Return JSON:
{{"fullScript":"Full transcript with timestamps","mainTopics":["topic 1","topic 2","topic 3"],"keyPoints":["point 1","point 2","point 3","point 4"],"hookUsed":"Description of the hook used"}}
Return JSON only, no additional text.""",

        'hook': f"""You are a YouTube hook expert. Analyze this video:

Title: {title}
Channel: {channel}
Views: {views}
Engagement: {engagement}%
{trans_preview and f'Transcript:\n{trans_preview}\n---\n' or ''}
Return JSON:
{{"hookAnalysis":"Detailed analysis of the hook - words used, psychological triggers, style","whyViral":["reason 1","reason 2","reason 3","reason 4","reason 5"],"suggestedHooks":["hook 1","hook 2","hook 3","hook 4","hook 5"]}}
Return JSON only.""",

        'script': f"""You are a professional YouTube script writer. Create a similar script for this video:

Title: {title}
Channel: {channel}
{trans_preview and f'Transcript:\n{trans_preview}\n---\n' or ''}
Return JSON:
{{"newHook":"Strong hook for first seconds - exact words","newScript":"Full script with timestamps and formatting","keyMoments":["moment 1","moment 2","moment 3","moment 4"]}}
Return JSON only.""",

        'titles': f"""You are a YouTube SEO expert. Suggest 10 titles for this video:

Original Title: {title}
Channel: {channel}
Views: {views}
{trans_preview and f'Content Summary:\n{trans_preview[:500]}\n' or ''}
Requirements:
- Each title under 60 characters
- Different from original title
- Use psychological triggers (curiosity, FOMO, numbers, emotion)
- Click-worthy

Return JSON array:
["title 1","title 2","title 3","title 4","title 5","title 6","title 7","title 8","title 9","title 10"]""",

        'desc': f"""You are a professional YouTube description writer. Write SEO description for this video:

Title: {title}
Channel: {channel}
{trans_preview and f'Content:\n{trans_preview[:800]}\n' or ''}
Return JSON:
{{"description":"Professional description 150-250 words - engaging opener, key points, timestamps, CTA","hashtags":"#hashtag1 #hashtag2 #hashtag3 ..."}}
Return JSON only."""
    }

    if tool not in prompts:
        return jsonify({'error': 'Invalid tool'}), 400

    if not client:
        return jsonify({'error': 'OpenAI API not configured'}), 500

    result = ask_ai(prompts[tool], "Return JSON only, no additional text.")

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
#  START
# ============================================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
