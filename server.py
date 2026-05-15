"""
YouTube AI Analyzer - Backend Server
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
from youtube_transcript_api import YouTubeTranscriptApi
import re
import os
from openai import OpenAI

app = Flask(__name__)
CORS(app)

OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
ytt_api = YouTubeTranscriptApi()

def extract_video_id(url_or_id):
    patterns = [
        r'(?:v=|youtu\.be\/|embed\/|shorts\/)([a-zA-Z0-9_-]{11})',
        r'^([a-zA-Z0-9_-]{11})$'
    ]
    for pattern in patterns:
        match = re.search(pattern, str(url_or_id))
        if match:
            return match.group(1)
    return None

def ask_ai(prompt, system_prompt="أنت مساعد ذكي"):
    if not client:
        return "❌ OpenAI API غير مربوط"
    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=2000
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"❌ خطأ: {str(e)}"

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        'status': 'ok',
        'openai_enabled': bool(client)
    })

@app.route('/transcript', methods=['GET'])
def get_transcript():
    video_id = request.args.get('video_id', '')
    if not video_id:
        return jsonify({'error': 'Video ID required'}), 400
    
    video_id = extract_video_id(video_id)
    if not video_id:
        return jsonify({'error': 'Invalid video ID'}), 400
    
    try:
        transcript = ytt_api.fetch(video_id, languages=['ar', 'en', 'es', 'de', 'fr', 'pt', 'it'])
        lines = []
        for entry in transcript:
            mins = int(entry.start) // 60
            secs = int(entry.start) % 60
            text = entry.text.replace('\n', ' ').strip()
            if text:
                lines.append(f"[{mins:02d}:{secs:02d}] {text}")
        return jsonify({'success': True, 'video_id': video_id, 'transcript': '\n'.join(lines)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/video-info', methods=['GET'])
def get_video_info():
    video_id = extract_video_id(request.args.get('video_id', ''))
    if not video_id:
        return jsonify({'error': 'Invalid video ID'}), 400
    try:
        import urllib.request, json
        url = f'https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json'
        with urllib.request.urlopen(url, timeout=10) as response:
            data = json.loads(response.read().decode())
            return jsonify({
                'success': True,
                'video_id': video_id,
                'title': data.get('title', ''),
                'author': data.get('author_name', ''),
                'thumbnail': f'https://img.youtube.com/vi/{video_id}/hqdefault.jpg'
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/ai/analyze', methods=['POST'])
def analyze():
    data = request.get_json()
    tool = data.get('tool', '')
    transcript = data.get('transcript', '')
    title = data.get('title', '')
    channel = data.get('channel', '')

    prompts = {
        'transcript': f"""Analyze this YouTube video:
Title: {title}
Channel: {channel}
Transcript: {transcript[:4000]}
Return JSON with: mainTopics (5-8), keyPoints (20), fullScript, hookUsed""",

        'hook': f"""Analyze hook for:
Title: {title}
Transcript: {transcript[:3000]}
Return JSON with: hookAnalysis, whyViral (5-7), suggestedHooks (10)""",

        'script': f"""Generate similar script:
Title: {title}
Transcript: {transcript[:3000]}
Return JSON with: newHook, newScript, keyMoments (5-7)""",

        'titles': f"""Generate 10 titles for:
{title}
Transcript: {transcript[:2000]}
Return JSON array of 10 titles""",

        'desc': f"""Generate description and hashtags:
Title: {title}
Transcript: {transcript[:2000]}
Return JSON with: description (300-500 words), hashtags (15)"""
    }

    if tool not in prompts:
        return jsonify({'error': 'Invalid tool'}), 400

    result = ask_ai(prompts[tool], "You are a YouTube content analyst. Return JSON only.")
    return jsonify({'success': True, 'result': result})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
