"""
YouTube AI Analyzer - Backend Server
بيستخدم لجلب الترجمة الحقيقية من فيديوهات يوتيوب + OpenAI AI
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
from youtube_transcript_api import YouTubeTranscriptApi
import re
import os
from openai import OpenAI

app = Flask(__name__)
CORS(app)

# إعداد OpenAI
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# إنشاء instance من YouTubeTranscriptApi
ytt_api = YouTubeTranscriptApi()

def extract_video_id(url_or_id):
    """استخراج الـ video ID من رابط يوتيوب"""
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
    """إرسال طلب لـ OpenAI"""
    if not client:
        return "❌ OpenAI API غير مربوط. يرجى إضافة OPENAI_API_KEY في إعدادات Render."
    
    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=1000
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"❌ خطأ: {str(e)}"

@app.route('/health', methods=['GET'])
def health_check():
    """فحص حالة السيرفر"""
    return jsonify({
        'status': 'ok',
        'message': 'YouTube Analyzer Backend is running!',
        'openai_enabled': bool(client)
    })

@app.route('/transcript', methods=['GET', 'POST'])
def get_transcript():
    """جلب الترجمة الكاملة لفيديو يوتيوب"""
    video_input = request.args.get('video_id') or request.args.get('url', '')
    
    if not video_input:
        return jsonify({'error': 'لم يتم توفير معرف الفيديو'}), 400
    
    video_id = extract_video_id(video_input)
    if not video_id:
        return jsonify({'error': 'رابط أو معرف فيديو غير صالح'}), 400
    
    try:
        transcript = ytt_api.fetch(
            video_id,
            languages=['ar', 'en', 'es', 'de', 'fr', 'pt', 'it']
        )
        
        formatted_lines = []
        for entry in transcript:
            start_seconds = int(entry.start)
            minutes = start_seconds // 60
            seconds = start_seconds % 60
            text = entry.text.replace('\n', ' ').strip()
            if text:
                formatted_lines.append(f"[{minutes:02d}:{seconds:02d}] {text}")
        
        full_transcript = '\n'.join(formatted_lines)
        
        return jsonify({
            'success': True,
            'video_id': video_id,
            'transcript': full_transcript
        })
    except Exception as e:
        error_message = str(e)
        if 'No transcripts were found' in error_message:
            return jsonify({'error': 'لا توجد ترجمة متاحة لهذا الفيديو', 'video_id': video_id}), 404
        elif 'Video unavailable' in error_message:
            return jsonify({'error': 'الفيديو غير متاح أو محذوف', 'video_id': video_id}), 404
        else:
            return jsonify({'error': f'حدث خطأ: {error_message}', 'video_id': video_id}), 500

@app.route('/video-info', methods=['GET'])
def get_video_info():
    """جلب معلومات الفيديو"""
    video_id = request.args.get('video_id')
    if not video_id:
        return jsonify({'error': 'معرف الفيديو مطلوب'}), 400
    try:
        video_id = extract_video_id(video_id)
        import urllib.request
        import json
        oembed_url = f'https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json'
        with urllib.request.urlopen(oembed_url, timeout=10) as response:
            data = json.loads(response.read().decode())
            return jsonify({
                'success': True,
                'video_id': video_id,
                'title': data.get('title', ''),
                'author': data.get('author_name', ''),
                'thumbnail': f'https://img.youtube.com/vi/{video_id}/hqdefault.jpg'
            })
    except Exception as e:
        return jsonify({'error': str(e), 'video_id': video_id}), 500

# ====== ميزات OpenAI ======

@app.route('/ai/hook-analysis', methods=['POST'])
def hook_analysis():
    """تحليل الهوك"""
    data = request.get_json()
    transcript = data.get('transcript', '')
    
    if not transcript:
        return jsonify({'error': 'الترجمة مطلوبة'}), 400
    
    prompt = f"""を分析 هذا الفيديو:
{transcript[:3000]}

أعطني:
1. أفضل 5 هوكات (فتحات) للفيديو
2. لماذا كل هوك يعمل
3. مثال على نص لكل هوك"""
    
    result = ask_ai(prompt, "أنت خبير في تحليل محتوى يوتيوب")
    return jsonify({'success': True, 'result': result})

@app.route('/ai/first-minute', methods=['POST'])
def first_minute():
    """اقتراح أول دقيقة"""
    data = request.get_json()
    transcript = data.get('transcript', '')
    
    if not transcript:
        return jsonify({'error': 'الترجمة مطلوبة'}), 400
    
    prompt = f"""بناءً على هذا المحتوى:
{transcript[:3000]}

أعطني:
1. أول 3 ثواني - جملة جذب الانتباه
2. أول 10 ثواني - فتح قوي
3. أول 30 ثانية - بناء الفضول
4. أول دقيقة كاملة - هيكل واضح"""
    
    result = ask_ai(prompt, "أنت خبير في كتابة سكريبت يوتيوب")
    return jsonify({'success': True, 'result': result})

@app.route('/ai/similar-script', methods=['POST'])
def similar_script():
    """اقتراح سكريبت مشابه"""
    data = request.get_json()
    transcript = data.get('transcript', '')
    
    if not transcript:
        return jsonify({'error': 'الترجمة مطلوبة'}), 400
    
    prompt = f"""بناءً على هذا الفيديو:
{transcript[:3000]}

اكتب لي سكريبت جديد للفيديو بنفس الأسلوب والهيكل"""
    
    result = ask_ai(prompt, "أنت كاتب محترف لسكريبت يوتيوب")
    return jsonify({'success': True, 'result': result})

@app.route('/ai/titles', methods=['POST'])
def generate_titles():
    """اقتراح عناوين"""
    data = request.get_json()
    transcript = data.get('transcript', '')
    
    if not transcript:
        return jsonify({'error': 'الترجمة مطلوبة'}), 400
    
    prompt = f"""بناءً على هذا الفيديو:
{transcript[:2000]}

أعطني 10 عناوين جذابة بالإنجليزية:
1. عنوان 1
2. عنوان 2
... (حتى 10)"""
    
    result = ask_ai(prompt, "أنت خبير في SEO وعناوين يوتيوب")
    return jsonify({'success': True, 'result': result})

@app.route('/ai/seo-titles', methods=['POST'])
def seo_titles():
    """عناوين SEO"""
    data = request.get_json()
    transcript = data.get('transcript', '')
    
    if not transcript:
        return jsonify({'error': 'الترجمة مطلوبة'}), 400
    
    prompt = f"""بناءً على هذا الفيديو:
{transcript[:2000]}

أعطني 10 عناوين SEO مثالية بالإنجليزية"""
    
    result = ask_ai(prompt, "أنت خبير في SEO")
    return jsonify({'success': True, 'result': result})

@app.route('/ai/description', methods=['POST'])
def description():
    """اقتراح وصف"""
    data = request.get_json()
    transcript = data.get('transcript', '')
    
    if not transcript:
        return jsonify({'error': 'الترجمة مطلوبة'}), 400
    
    prompt = f"""بناءً على هذا الفيديو:
{transcript[:2000]}

أعطني:
1. وصف كامل (300-500 كلمة)
2. 15 هاشتاق مناسب"""
    
    result = ask_ai(prompt, "أنت خبير في كتابة وصف يوتيوب")
    return jsonify({'success': True, 'result': result})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
