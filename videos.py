from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak, KeepTogether
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.platypus import Flowable

W, H = A4

# ── Colour palette ──────────────────────────────────────────────────────────
DARK_BG    = colors.HexColor('#0D1117')
BLUE       = colors.HexColor('#1E90FF')
BLUE_LIGHT = colors.HexColor('#4FAAFF')
GREEN      = colors.HexColor('#2EA44F')
ORANGE     = colors.HexColor('#E36209')
RED        = colors.HexColor('#CF222E')
CARD_BG    = colors.HexColor('#161B22')
BORDER     = colors.HexColor('#30363D')
TEXT_MAIN  = colors.HexColor('#E6EDF3')
TEXT_SUB   = colors.HexColor('#8B949E')
CODE_BG    = colors.HexColor('#0D1117')
CODE_FG    = colors.HexColor('#79C0FF')
WHITE      = colors.white

# ── Styles ──────────────────────────────────────────────────────────────────
base_styles = getSampleStyleSheet()

def make_style(name, **kw):
    return ParagraphStyle(name, **kw)

S = {
    'h_title': make_style('HTitle',
        fontName='Helvetica-Bold', fontSize=26, textColor=WHITE,
        spaceAfter=4, alignment=TA_CENTER),
    'h_sub': make_style('HSub',
        fontName='Helvetica', fontSize=13, textColor=BLUE_LIGHT,
        spaceAfter=2, alignment=TA_CENTER),
    'h_meta': make_style('HMeta',
        fontName='Helvetica', fontSize=9, textColor=TEXT_SUB,
        spaceAfter=0, alignment=TA_CENTER),
    'section': make_style('Section',
        fontName='Helvetica-Bold', fontSize=14, textColor=WHITE,
        spaceBefore=14, spaceAfter=6),
    'step_title': make_style('StepTitle',
        fontName='Helvetica-Bold', fontSize=12, textColor=BLUE_LIGHT,
        spaceBefore=10, spaceAfter=4),
    'file_label': make_style('FileLabel',
        fontName='Helvetica-Bold', fontSize=9, textColor=ORANGE,
        spaceBefore=4, spaceAfter=2),
    'body': make_style('Body',
        fontName='Helvetica', fontSize=9, textColor=TEXT_MAIN,
        leading=14, spaceAfter=4),
    'code': make_style('Code',
        fontName='Courier', fontSize=8, textColor=CODE_FG,
        leading=12, spaceAfter=2, leftIndent=8),
    'code_comment': make_style('CodeComment',
        fontName='Courier', fontSize=8, textColor=TEXT_SUB,
        leading=12, leftIndent=8),
    'bullet': make_style('Bullet',
        fontName='Helvetica', fontSize=9, textColor=TEXT_MAIN,
        leading=14, leftIndent=14, spaceAfter=2),
    'priority_high': make_style('PH',
        fontName='Helvetica-Bold', fontSize=8, textColor=RED),
    'priority_med': make_style('PM',
        fontName='Helvetica-Bold', fontSize=8, textColor=ORANGE),
    'priority_low': make_style('PL',
        fontName='Helvetica-Bold', fontSize=8, textColor=GREEN),
    'toc_item': make_style('TOC',
        fontName='Helvetica', fontSize=9, textColor=TEXT_MAIN,
        leading=16, leftIndent=10),
}

# ── Custom Flowables ─────────────────────────────────────────────────────────
class ColorRect(Flowable):
    def __init__(self, width, height, fill, radius=4):
        self.w, self.h, self.fill, self.r = width, height, fill, radius
    def draw(self):
        self.canv.setFillColor(self.fill)
        self.canv.roundRect(0, 0, self.w, self.h, self.r, fill=1, stroke=0)
    def wrap(self, *args): return self.w, self.h

class StepBadge(Flowable):
    """Numbered step badge circle."""
    def __init__(self, num, color=BLUE):
        self.num, self.color = num, color
        Flowable.__init__(self)
    def draw(self):
        c = self.canv
        c.setFillColor(self.color)
        c.circle(10, 6, 10, fill=1, stroke=0)
        c.setFillColor(WHITE)
        c.setFont('Helvetica-Bold', 9)
        c.drawCentredString(10, 2.5, str(self.num))
    def wrap(self, *args): return 22, 18

def hr(color=BORDER, thickness=0.5):
    return HRFlowable(width='100%', thickness=thickness, color=color,
                      spaceAfter=6, spaceBefore=6)

def spacer(h=6):
    return Spacer(1, h)

def code_block(lines):
    """Render a code block as a table with dark background."""
    content = []
    for line in lines:
        stripped = line.lstrip()
        style = S['code_comment'] if stripped.startswith('#') else S['code']
        content.append(Paragraph(line.replace(' ', '&nbsp;').replace('<', '&lt;').replace('>', '&gt;'), style))
    tbl = Table([[content]], colWidths=[155*mm])
    tbl.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), CODE_BG),
        ('ROUNDEDCORNERS', [4]),
        ('TOPPADDING',    (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ('LEFTPADDING',   (0,0), (-1,-1), 10),
        ('RIGHTPADDING',  (0,0), (-1,-1), 8),
        ('BOX', (0,0), (-1,-1), 0.5, BORDER),
    ]))
    return tbl

def file_tag(filename, action='Edit'):
    """Orange file tag."""
    return Paragraph(f'📄 FILE: <b>{filename}</b>  |  Action: {action}', S['file_label'])

def info_box(text, color=BLUE):
    # Create a lighter background color manually
    bg_color = colors.Color(
        min(color.red + 0.07, 1),
        min(color.green + 0.07, 1),
        min(color.blue + 0.07, 1),
        alpha=1
    )

    tbl = Table([[Paragraph(text, S['body'])]], colWidths=[155*mm])

    tbl.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), bg_color),
        ('LEFTPADDING', (0,0), (-1,-1), 10),
        ('RIGHTPADDING', (0,0), (-1,-1), 10),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('BOX', (0,0), (-1,-1), 1, color),
        ('ROUNDEDCORNERS', [4]),
    ]))

    return tbl
# ── Cover page builder ───────────────────────────────────────────────────────
def cover_page():
    elems = []
    elems.append(spacer(40))
    # Big header card
    tbl = Table([[
        Paragraph('ConnectDial', S['h_title']),
    ]], colWidths=[155*mm])
    tbl.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), DARK_BG),
        ('TOPPADDING', (0,0), (-1,-1), 30),
        ('BOTTOMPADDING', (0,0), (-1,-1), 10),
        ('BOX', (0,0), (-1,-1), 1, BLUE),
        ('ROUNDEDCORNERS', [8]),
    ]))
    elems.append(tbl)
    elems.append(spacer(4))
    elems.append(Paragraph('Short Video Feature — Backend &amp; Frontend', S['h_sub']))
    elems.append(Paragraph('Upload Optimization &amp; Feed Speed Implementation Guide', S['h_sub']))
    elems.append(spacer(6))
    elems.append(Paragraph('Version 1.0 · May 2026 · Titus Tech Services', S['h_meta']))
    elems.append(spacer(30))
    hr(BLUE, 1)
    elems.append(spacer(10))

    # Summary cards row
    cards = [
        ('10', 'Total Steps'),
        ('5', 'Backend Files'),
        ('1', 'Frontend File'),
        ('3', 'Priority Levels'),
    ]
    card_rows = []
    for val, label in cards:
        cell = [
            Paragraph(f'<b>{val}</b>', ParagraphStyle('CV', fontName='Helvetica-Bold',
                fontSize=22, textColor=BLUE_LIGHT, alignment=TA_CENTER)),
            Paragraph(label, ParagraphStyle('CL', fontName='Helvetica',
                fontSize=8, textColor=TEXT_SUB, alignment=TA_CENTER)),
        ]
        card_rows.append(cell)

    summary = Table([card_rows], colWidths=[37*mm]*4)
    summary.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), CARD_BG),
        ('BOX', (0,0), (-1,-1), 0.5, BORDER),
        ('INNERGRID', (0,0), (-1,-1), 0.5, BORDER),
        ('TOPPADDING', (0,0), (-1,-1), 10),
        ('BOTTOMPADDING', (0,0), (-1,-1), 10),
        ('ROUNDEDCORNERS', [4]),
    ]))
    elems.append(summary)
    elems.append(spacer(20))

    # TOC
    elems.append(Paragraph('TABLE OF CONTENTS', ParagraphStyle('TOCH',
        fontName='Helvetica-Bold', fontSize=10, textColor=BLUE,
        spaceAfter=8)))
    hr(BORDER)

    toc_items = [
        ('BACKEND', [
            ('Step 1', 'views.py', 'Upload endpoint with duration extraction'),
            ('Step 2', 'views.py + settings.py', 'Video compression with ffmpeg (-movflags +faststart)'),
            ('Step 3', 'views.py', 'Auto-generate thumbnail on upload'),
            ('Step 4', 'views.py', 'Fix feed pagination (Twitter-style)'),
            ('Step 5', 'feed_algorithm.py', 'Fix N+1 queries with select_related'),
            ('Step 6', 'settings.py', 'Confirm Redis caching setup'),
            ('Step 7', 'views.py', 'Add streaming view with Range request support'),
        ]),
        ('FRONTEND', [
            ('Step 8',  'ShortsScreen.jsx', 'FlatList performance (getItemLayout + windowSize)'),
            ('Step 9',  'ShortsScreen.jsx', 'Preload next video before swipe'),
            ('Step 10', 'PostScreen.jsx (new)', 'Upload with progress bar'),
        ]),
    ]
    for section, items in toc_items:
        elems.append(Paragraph(f'<b>{section}</b>', ParagraphStyle('TH',
            fontName='Helvetica-Bold', fontSize=9, textColor=BLUE_LIGHT,
            spaceBefore=8, spaceAfter=4)))
        for step, fname, desc in items:
            row = Table([[
                Paragraph(f'<b>{step}</b>', ParagraphStyle('TS', fontName='Helvetica-Bold',
                    fontSize=9, textColor=BLUE)),
                Paragraph(fname, ParagraphStyle('TF', fontName='Courier',
                    fontSize=8, textColor=ORANGE)),
                Paragraph(desc, S['toc_item']),
            ]], colWidths=[18*mm, 55*mm, 82*mm])
            row.setStyle(TableStyle([
                ('TOPPADDING', (0,0), (-1,-1), 3),
                ('BOTTOMPADDING', (0,0), (-1,-1), 3),
                ('LEFTPADDING', (0,0), (0,0), 10),
            ]))
            elems.append(row)

    elems.append(PageBreak())
    return elems

# ── Priority table ────────────────────────────────────────────────────────────
def priority_table():
    elems = []
    elems.append(Paragraph('IMPLEMENTATION PRIORITY', ParagraphStyle('PT',
        fontName='Helvetica-Bold', fontSize=11, textColor=WHITE, spaceAfter=8)))
    data = [
        [Paragraph('<b>Priority</b>', S['body']),
         Paragraph('<b>Step</b>', S['body']),
         Paragraph('<b>File</b>', S['body']),
         Paragraph('<b>Impact</b>', S['body'])],
        [Paragraph('🔴 DO FIRST', S['priority_high']),
         Paragraph('Step 2 — ffmpeg +faststart', S['body']),
         Paragraph('views.py', ParagraphStyle('MF', fontName='Courier', fontSize=8, textColor=ORANGE)),
         Paragraph('Biggest speed win — instant playback', S['body'])],
        [Paragraph('🔴 DO FIRST', S['priority_high']),
         Paragraph('Step 5 — N+1 query fix', S['body']),
         Paragraph('feed_algorithm.py', ParagraphStyle('MF', fontName='Courier', fontSize=8, textColor=ORANGE)),
         Paragraph('Stops DB overload on feed requests', S['body'])],
        [Paragraph('🟡 DO SECOND', S['priority_med']),
         Paragraph('Step 8 — getItemLayout', S['body']),
         Paragraph('ShortsScreen.jsx', ParagraphStyle('MF', fontName='Courier', fontSize=8, textColor=ORANGE)),
         Paragraph('Smooth scroll, no measurement lag', S['body'])],
        [Paragraph('🟡 DO SECOND', S['priority_med']),
         Paragraph('Step 6 — Redis confirm', S['body']),
         Paragraph('settings.py', ParagraphStyle('MF', fontName='Courier', fontSize=8, textColor=ORANGE)),
         Paragraph('Feed caching reduces DB hits', S['body'])],
        [Paragraph('🟢 DO LATER', S['priority_low']),
         Paragraph('Step 10 — CDN (S3+CloudFront)', S['body']),
         Paragraph('settings.py', ParagraphStyle('MF', fontName='Courier', fontSize=8, textColor=ORANGE)),
         Paragraph('Production scale — global delivery', S['body'])],
    ]
    t = Table(data, colWidths=[28*mm, 50*mm, 38*mm, 39*mm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), BLUE),
        ('BACKGROUND', (0,1), (-1,-1), CARD_BG),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [CARD_BG, DARK_BG]),
        ('TEXTCOLOR', (0,0), (-1,0), WHITE),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 8),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
        ('BOX', (0,0), (-1,-1), 0.5, BORDER),
        ('INNERGRID', (0,0), (-1,-1), 0.3, BORDER),
        ('ROUNDEDCORNERS', [4]),
    ]))
    elems.append(t)
    return elems

# ── Step builder helper ──────────────────────────────────────────────────────
def step_header(num, title, filename, action='Edit', priority='med'):
    color = RED if priority == 'high' else (ORANGE if priority == 'med' else GREEN)
    priority_text = '🔴 HIGH PRIORITY' if priority == 'high' else ('🟡 MEDIUM' if priority == 'med' else '🟢 LATER')
    row = Table([[
        Paragraph(f'<b>STEP {num}</b>', ParagraphStyle('SN', fontName='Helvetica-Bold',
            fontSize=16, textColor=BLUE_LIGHT)),
        Paragraph(title, ParagraphStyle('ST', fontName='Helvetica-Bold',
            fontSize=12, textColor=WHITE, leading=16)),
        Paragraph(priority_text, ParagraphStyle('SP', fontName='Helvetica-Bold',
            fontSize=8, textColor=color, alignment=TA_CENTER)),
    ]], colWidths=[22*mm, 100*mm, 33*mm])
    row.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), CARD_BG),
        ('BOX', (0,0), (-1,-1), 1, BLUE),
        ('LEFTBORDER', (0,0), (0,-1), 4, BLUE),
        ('TOPPADDING', (0,0), (-1,-1), 10),
        ('BOTTOMPADDING', (0,0), (-1,-1), 10),
        ('LEFTPADDING', (0,0), (-1,-1), 12),
        ('ROUNDEDCORNERS', [4]),
    ]))
    return row

# ── All steps content ────────────────────────────────────────────────────────
def all_steps():
    elems = []

    # ── BACKEND SECTION HEADER ──────────────────────────────────────────────
    elems.append(Paragraph('⚙️  BACKEND STEPS', S['section']))
    elems.append(hr(BLUE, 1))
    elems.append(spacer(8))

    # ── STEP 1 ──────────────────────────────────────────────────────────────
    elems.append(KeepTogether([
        step_header(1, 'Upload Endpoint — Auto-extract Duration', 'views.py', priority='med'),
        spacer(6),
        file_tag('shorts/views.py', 'ADD new upload view class'),
        Paragraph('Create a dedicated upload view that accepts video files, auto-extracts duration using ffprobe, and returns the full serialized video immediately.', S['body']),
        spacer(4),
        code_block([
            '# shorts/views.py — ADD this import at the top',
            'import subprocess, tempfile, os',
            '',
            '# ADD this helper function',
            'def extract_duration(file_path):',
            '    result = subprocess.run([',
            "        'ffprobe', '-v', 'error',",
            "        '-show_entries', 'format=duration',",
            "        '-of', 'default=noprint_wrappers=1:nokey=1',",
            '        file_path',
            '    ], capture_output=True, text=True)',
            '    try:',
            '        return int(float(result.stdout.strip()))',
            '    except:',
            '        return 0',
            '',
            '# ADD this new view class',
            'class ShortVideoUploadView(generics.CreateAPIView):',
            '    serializer_class  = ShortVideoSerializer',
            '    permission_classes = [IsAuthenticated]',
            '    parser_classes    = [MultiPartParser, FormParser]',
            '',
            '    def perform_create(self, serializer):',
            '        video_file = self.request.FILES.get("video")',
            '        duration   = 0',
            '        if video_file:',
            '            with tempfile.NamedTemporaryFile(delete=False,',
            '                    suffix=".mp4") as tmp:',
            '                for chunk in video_file.chunks():',
            '                    tmp.write(chunk)',
            '                tmp_path = tmp.name',
            '            duration = extract_duration(tmp_path)',
            '            os.unlink(tmp_path)',
            '        serializer.save(author=self.request.user, duration=duration)',
        ]),
        spacer(4),
        file_tag('shorts/urls.py', 'ADD upload URL'),
        code_block([
            "# ADD this line inside urlpatterns list in shorts/urls.py",
            "path('shorts/upload/', views.ShortVideoUploadView.as_view(),",
            "     name='short-video-upload'),",
        ]),
    ]))
    elems.append(spacer(16))

    # ── STEP 2 ──────────────────────────────────────────────────────────────
    elems.append(KeepTogether([
        step_header(2, 'Video Compression — ffmpeg +faststart Flag', 'views.py', priority='high'),
        spacer(6),
        info_box('🔴 MOST IMPORTANT STEP — The -movflags +faststart flag moves the MP4 header to the start of the file. Without it, mobile players must download the entire file before playback begins. With it, playback starts in ~1 second.', RED),
        spacer(6),
        file_tag('shorts/views.py', 'ADD compress_video helper + call in upload view'),
        code_block([
            '# shorts/views.py — ADD this function after extract_duration()',
            '',
            'def compress_video(input_path: str, output_path: str):',
            '    """',
            '    Compress video with H.264 + AAC and write MP4 header',
            '    at the START of the file (+faststart) for instant',
            '    mobile playback without full-file download.',
            '    """',
            '    subprocess.run([',
            "        'ffmpeg', '-i', input_path,",
            "        '-vcodec', 'libx264',",
            "        '-crf',    '28',       # 23-28 sweet spot (lower = better)",
            "        '-preset', 'fast',     # encoding speed",
            "        '-acodec', 'aac',",
            "        '-b:a',    '128k',",
            "        '-movflags', '+faststart',  # ← THE KEY FLAG",
            "        '-y',",
            '        output_path',
            '    ], check=True)',
            '',
            '# MODIFY perform_create inside ShortVideoUploadView',
            '    def perform_create(self, serializer):',
            '        video_file = self.request.FILES.get("video")',
            '        duration   = 0',
            '        compressed_path = None',
            '        if video_file:',
            '            with tempfile.NamedTemporaryFile(delete=False,',
            '                    suffix=".mp4") as tmp:',
            '                for chunk in video_file.chunks():',
            '                    tmp.write(chunk)',
            '                tmp_path = tmp.name',
            '            compressed_path = tmp_path + "_compressed.mp4"',
            '            compress_video(tmp_path, compressed_path)',
            '            duration = extract_duration(compressed_path)',
            '            os.unlink(tmp_path)',
            '        serializer.save(author=self.request.user,',
            '                        duration=duration)',
            '        if compressed_path:',
            '            os.unlink(compressed_path)',
        ]),
    ]))
    elems.append(spacer(16))

    # ── STEP 3 ──────────────────────────────────────────────────────────────
    elems.append(KeepTogether([
        step_header(3, 'Auto-generate Thumbnail on Upload', 'views.py', priority='med'),
        spacer(6),
        file_tag('shorts/views.py', 'ADD generate_thumbnail helper + call in upload view'),
        Paragraph('Automatically grab a frame at 1 second and save as thumbnail. No manual upload needed from the client.', S['body']),
        spacer(4),
        code_block([
            '# shorts/views.py — ADD after compress_video()',
            '',
            'from django.core.files.base import ContentFile',
            '',
            'def generate_thumbnail(video_path: str) -> bytes:',
            '    """Extract frame at 1s, return JPEG bytes."""',
            '    with tempfile.NamedTemporaryFile(suffix=".jpg",',
            '                                    delete=False) as thumb:',
            '        thumb_path = thumb.name',
            '    subprocess.run([',
            "        'ffmpeg', '-i', video_path,",
            "        '-ss', '00:00:01',",
            "        '-vframes', '1',",
            "        '-vf', 'scale=480:-1',",
            "        '-y', thumb_path",
            '    ], check=True)',
            '    with open(thumb_path, "rb") as f:',
            '        data = f.read()',
            '    os.unlink(thumb_path)',
            '    return data',
            '',
            '# MODIFY perform_create — add thumbnail save',
            '    def perform_create(self, serializer):',
            '        ...  # (keep existing code)',
            '        instance = serializer.save(author=self.request.user,',
            '                                   duration=duration)',
            '        # Auto-generate thumbnail if none uploaded',
            '        if compressed_path and not instance.thumbnail:',
            '            thumb_bytes = generate_thumbnail(compressed_path)',
            '            instance.thumbnail.save(',
            '                f"thumb_{instance.pk}.jpg",',
            '                ContentFile(thumb_bytes), save=True',
            '            )',
        ]),
    ]))
    elems.append(spacer(16))

    # ── STEP 4 ──────────────────────────────────────────────────────────────
    elems.append(KeepTogether([
        step_header(4, 'Fix Feed Pagination — Twitter-style', 'views.py', priority='med'),
        spacer(6),
        file_tag('shorts/views.py', 'EDIT ShortVideoFeedView — add proper pagination'),
        Paragraph('Your current feed returns flat results. Add cursor/offset pagination with proper count so React Native can implement infinite scroll correctly.', S['body']),
        spacer(4),
        code_block([
            '# shorts/views.py — EDIT ShortVideoFeedView',
            '',
            'from rest_framework.pagination import LimitOffsetPagination',
            '',
            'class ShortVideoPagination(LimitOffsetPagination):',
            '    default_limit = 10',
            '    max_limit     = 20',
            '',
            'class ShortVideoFeedView(generics.ListAPIView):',
            '    serializer_class   = ShortVideoSerializer',
            '    permission_classes = [IsAuthenticated]',
            '    pagination_class   = ShortVideoPagination',
            '',
            '    def get_queryset(self):',
            '        return get_short_video_feed(',
            '            self.request.user,',
            '            limit=int(self.request.query_params.get("limit", 10)),',
            '            bypass_cache=False,',
            '        )',
            '',
            '    def list(self, request, *args, **kwargs):',
            '        qs         = self.get_queryset()',
            '        page       = self.paginate_queryset(list(qs))',
            '        serializer = self.get_serializer(',
            '            page or qs, many=True,',
            '            context={"request": request}',
            '        )',
            '        if page is not None:',
            '            return self.get_paginated_response(serializer.data)',
            '        return Response({"results": serializer.data,',
            '                         "count": len(serializer.data)})',
        ]),
    ]))
    elems.append(spacer(16))

    # ── STEP 5 ──────────────────────────────────────────────────────────────
    elems.append(KeepTogether([
        step_header(5, 'Fix N+1 Queries — select_related + prefetch_related', 'feed_algorithm.py', priority='high'),
        spacer(6),
        info_box('🔴 HIGH IMPACT — Without this fix, every feed request of 10 videos runs ~50+ DB queries (one per author avatar, profile, etc). After this fix: 4-5 queries total.', RED),
        spacer(6),
        file_tag('shorts/feed_algorithm.py', 'EDIT get_short_video_feed — base queryset section'),
        Paragraph("Find the line that says '# ── 2. Base queryset' and replace it:", S['body']),
        spacer(4),
        code_block([
            '# feed_algorithm.py — EDIT section "2. Base queryset"',
            '# FIND THIS (around line 120):',
            "qs = ShortVideo.objects.select_related('author', 'league', 'team')",
            '',
            '# REPLACE WITH:',
            'qs = ShortVideo.objects.select_related(',
            "    'author',",
            "    'author__profile',   # ← fetches avatar in 1 query",
            "    'league',",
            "    'team',",
            ').prefetch_related(',
            "    'likes',             # ← for is_liked check in serializer",
            "    'comments',          # ← for comments_count fallback",
            ')',
        ]),
        spacer(6),
        file_tag('shorts/serializers.py', 'EDIT get_is_liked — use prefetched data'),
        code_block([
            '# serializers.py — EDIT get_is_liked method in ShortVideoSerializer',
            '# FIND:',
            '    def get_is_liked(self, obj):',
            '        request = self.context.get("request")',
            '        if request and request.user.is_authenticated:',
            '            return obj.likes.filter(user=request.user).exists()',
            '        return False',
            '',
            '# REPLACE WITH (uses prefetched cache — no extra DB hit):',
            '    def get_is_liked(self, obj):',
            '        request = self.context.get("request")',
            '        if request and request.user.is_authenticated:',
            '            uid = request.user.pk',
            '            # Use prefetch cache if available',
            '            if hasattr(obj, "_prefetched_objects_cache")',
            '                    and "likes" in obj._prefetched_objects_cache:',
            '                return any(l.user_id == uid',
            '                           for l in obj.likes.all())',
            '            return obj.likes.filter(user_id=uid).exists()',
            '        return False',
        ]),
    ]))
    elems.append(spacer(16))

    # ── STEP 6 ──────────────────────────────────────────────────────────────
    elems.append(KeepTogether([
        step_header(6, 'Confirm Redis Caching — settings.py', 'settings.py', priority='med'),
        spacer(6),
        file_tag('connectdial/settings.py', 'ADD Redis cache config'),
        Paragraph("Your feed_algorithm.py already uses Django's cache framework. Make sure settings.py points it at Redis, not the default in-memory cache (which resets on every request).", S['body']),
        spacer(4),
        code_block([
            '# connectdial/settings.py — ADD or REPLACE the CACHES block',
            '',
            'CACHES = {',
            '    "default": {',
            '        "BACKEND": "django_redis.cache.RedisCache",',
            '        "LOCATION": "redis://127.0.0.1:6379/1",',
            '        "OPTIONS": {',
            '            "CLIENT_CLASS": "django_redis.client.DefaultClient",',
            '            "SOCKET_CONNECT_TIMEOUT": 5,',
            '            "SOCKET_TIMEOUT": 5,',
            '        },',
            '        "KEY_PREFIX": "connectdial",',
            '    }',
            '}',
            '',
            '# INSTALL: pip install django-redis',
            '# ALSO make sure Redis is running:',
            '# Ubuntu/WSL:  sudo service redis-server start',
            '# Windows:     use Redis for Windows or WSL',
        ]),
    ]))
    elems.append(spacer(16))

    # ── STEP 7 ──────────────────────────────────────────────────────────────
    elems.append(KeepTogether([
        step_header(7, 'Streaming View — HTTP Range Request Support', 'views.py', priority='med'),
        spacer(6),
        file_tag('shorts/views.py', 'VERIFY ShortVideoStreamView uses streaming.py'),
        Paragraph('Your streaming.py is already complete. Make sure your ShortVideoStreamView calls stream_video_response() and authenticates via token query param (for react-native-video).', S['body']),
        spacer(4),
        code_block([
            '# shorts/views.py — VERIFY or ADD ShortVideoStreamView',
            '',
            'from rest_framework.authtoken.models import Token',
            'from .streaming import stream_video_response',
            '',
            'class ShortVideoStreamView(APIView):',
            '    authentication_classes = []  # manual auth below',
            '    permission_classes     = [AllowAny]',
            '',
            '    def get(self, request, pk):',
            '        # Authenticate via ?token= query param',
            '        # (react-native-video cannot set Auth headers on src URL)',
            '        token_key = request.query_params.get("token")',
            '        if token_key:',
            '            try:',
            '                token = Token.objects.select_related("user").get(',
            '                    key=token_key)',
            '                request.user = token.user',
            '            except Token.DoesNotExist:',
            '                return Response({"detail": "Invalid token."},',
            '                    status=401)',
            '        video = get_object_or_404(ShortVideo, pk=pk)',
            '        return stream_video_response(request, video)',
        ]),
    ]))
    elems.append(PageBreak())

    # ── FRONTEND SECTION HEADER ─────────────────────────────────────────────
    elems.append(Paragraph('📱  FRONTEND STEPS', S['section']))
    elems.append(hr(BLUE, 1))
    elems.append(spacer(8))

    # ── STEP 8 ──────────────────────────────────────────────────────────────
    elems.append(KeepTogether([
        step_header(8, 'FlatList Performance — getItemLayout + windowSize', 'ShortsScreen.jsx', priority='high'),
        spacer(6),
        info_box('🟡 MEDIUM — getItemLayout eliminates the measurement lag that causes janky scroll. Without it, React Native measures each item height at runtime, causing visible stutters when swiping.', ORANGE),
        spacer(6),
        file_tag('src/screens/ShortsScreen.jsx', 'EDIT FlatList props'),
        Paragraph("Find your FlatList component and add/update these props:", S['body']),
        spacer(4),
        code_block([
            '// ShortsScreen.jsx — EDIT the <FlatList> component',
            '// FIND your existing FlatList and ADD/CHANGE these props:',
            '',
            '<FlatList',
            '  data={shorts}',
            '  keyExtractor={item => String(item.id)}',
            '  renderItem={({ item, index }) => (',
            '    <ShortItem',
            '      item={item}',
            '      nextItem={shorts[index + 1] || null}  // ← ADD',
            '      isVisible={isFocused && index === viewableIndex}',
            '      navigation={navigation}',
            '      theme={theme}',
            '    />',
            '  )}',
            '',
            '  // ← ADD: tells FlatList exact heights — no runtime measuring',
            '  getItemLayout={(data, index) => ({',
            '    length: SCREEN_HEIGHT,',
            '    offset: SCREEN_HEIGHT * index,',
            '    index,',
            '  })}',
            '',
            '  // ← CHANGE: was 3, now 5 — more pre-rendered items',
            '  windowSize={5}',
            '  initialNumToRender={3}',
            '  maxToRenderPerBatch={5}',
            '',
            '  // ← CHANGE: reduce from 10 to 5 — faster first load',
            '  // (update const PAGE_SIZE = 5 at top of file)',
            '',
            '  pagingEnabled',
            '  snapToInterval={SCREEN_HEIGHT}',
            '  snapToAlignment="start"',
            '  decelerationRate="fast"',
            '  disableIntervalMomentum',
            '  showsVerticalScrollIndicator={false}',
            '  // ... rest of your existing props',
            '/>',
        ]),
        spacer(4),
        file_tag('src/screens/ShortsScreen.jsx', 'CHANGE PAGE_SIZE constant'),
        code_block([
            '// FIND at top of ShortsScreen.jsx:',
            'const PAGE_SIZE = 10;',
            '',
            '// CHANGE TO:',
            'const PAGE_SIZE = 5;  // Fewer items = faster first load feel',
        ]),
    ]))
    elems.append(spacer(16))

    # ── STEP 9 ──────────────────────────────────────────────────────────────
    elems.append(KeepTogether([
        step_header(9, 'Preload Next Video Before User Swipes', 'ShortsScreen.jsx', priority='med'),
        spacer(6),
        file_tag('src/screens/ShortsScreen.jsx', 'EDIT ShortItem component — add nextItem prop + preload'),
        Paragraph('Mount the next video (paused + muted) while user watches the current one. When they swipe, it starts instantly because buffering is already done.', S['body']),
        spacer(4),
        code_block([
            '// ShortsScreen.jsx — EDIT ShortItem component signature',
            '// FIND:',
            'const ShortItem = memo(({ item, isVisible, navigation, theme }) => {',
            '',
            '// CHANGE TO:',
            'const ShortItem = memo(({ item, nextItem, isVisible,',
            '                          navigation, theme }) => {',
            '',
            '  // ADD inside ShortItem, after existing state declarations:',
            '  // Pre-mount next video (hidden, paused) so it buffers early',
            '  const nextVideoUri = nextItem?.video_url || null;',
            '',
            '  // ... rest of existing component code ...',
            '',
            '  return (',
            '    <View style={styles.videoContainer}>',
            '      {/* Your existing Video player */}',
            '      <Video ... />',
            '',
            '      {/* ADD: Hidden preloader for next video */}',
            '      {nextVideoUri && (',
            '        <Video',
            '          source={{ uri: nextVideoUri }}',
            '          style={{ width: 1, height: 1, opacity: 0,',
            '                   position: "absolute", top: -9999 }}',
            '          paused={true}',
            '          muted={true}',
            '          bufferConfig={{',
            '            minBufferMs: 5000,',
            '            maxBufferMs: 15000,',
            '            bufferForPlaybackMs: 2000,',
            '            bufferForPlaybackAfterRebufferMs: 3000,',
            '          }}',
            '        />',
            '      )}',
            '',
            '      {/* ... rest of your JSX ... */}',
            '    </View>',
            '  );',
            '});',
        ]),
    ]))
    elems.append(spacer(16))

    # ── STEP 10 ──────────────────────────────────────────────────────────────
    elems.append(KeepTogether([
        step_header(10, 'Upload Screen — Progress Bar + Multipart Upload', 'PostScreen.jsx (CREATE NEW)', priority='low'),
        spacer(6),
        file_tag('src/screens/PostScreen.jsx', 'CREATE new file'),
        Paragraph('Create a Post/Upload screen that shows a progress bar during upload. Uses multipart/form-data to send the video, caption, league, and team to your new upload endpoint.', S['body']),
        spacer(4),
        code_block([
            '// src/screens/PostScreen.jsx — CREATE this file',
            '',
            "import React, { useState } from 'react';",
            "import { View, Text, TouchableOpacity, TextInput,",
            "         StyleSheet, Alert, ActivityIndicator } from 'react-native';",
            "import * as ImagePicker from 'expo-image-picker';",
            "import api from '../api/client';",
            '',
            'export default function PostScreen({ navigation }) {',
            '  const [videoUri, setVideoUri] = useState(null);',
            '  const [caption, setCaption]   = useState("");',
            '  const [progress, setProgress] = useState(0);',
            '  const [uploading, setUploading] = useState(false);',
            '',
            '  const pickVideo = async () => {',
            '    const result = await ImagePicker.launchImageLibraryAsync({',
            "      mediaTypes: ImagePicker.MediaTypeOptions.Videos,",
            '      quality: 1,',
            '    });',
            '    if (!result.canceled) {',
            '      setVideoUri(result.assets[0].uri);',
            '    }',
            '  };',
            '',
            '  const uploadVideo = async () => {',
            '    if (!videoUri) return;',
            '    setUploading(true);',
            '    setProgress(0);',
            '    const form = new FormData();',
            "    form.append('video', {",
            '      uri: videoUri,',
            "      type: 'video/mp4',",
            "      name: 'upload.mp4',",
            '    });',
            "    form.append('caption', caption);",
            '    try {',
            "      await api.post('api/videos/shorts/upload/', form, {",
            "        headers: { 'Content-Type': 'multipart/form-data' },",
            '        onUploadProgress: (e) => {',
            '          const pct = Math.round((e.loaded * 100) / e.total);',
            '          setProgress(pct);',
            '        },',
            '      });',
            "      Alert.alert('Posted!', 'Your video is live.');",
            '      navigation.goBack();',
            '    } catch (err) {',
            "      Alert.alert('Error', 'Upload failed. Try again.');",
            '    } finally {',
            '      setUploading(false);',
            '    }',
            '  };',
            '',
            '  return (',
            '    <View style={styles.container}>',
            "      <TouchableOpacity onPress={pickVideo} style={styles.pickBtn}>",
            "        <Text style={styles.pickText}>",
            "          {videoUri ? 'Video Selected ✓' : 'Pick Video'}",
            '        </Text>',
            '      </TouchableOpacity>',
            '      <TextInput',
            '        style={styles.input}',
            '        placeholder="Add a caption..."',
            '        value={caption}',
            '        onChangeText={setCaption}',
            '        multiline maxLength={2200}',
            '      />',
            '      {uploading && (',
            '        <View style={styles.progressBar}>',
            '          <View style={[styles.progressFill,',
            '            { width: `${progress}%` }]} />',
            '        </View>',
            '      )}',
            '      <TouchableOpacity',
            '        style={[styles.uploadBtn,',
            '          (!videoUri || uploading) && styles.disabled]}',
            '        onPress={uploadVideo}',
            '        disabled={!videoUri || uploading}',
            '      >',
            "        {uploading",
            '          ? <ActivityIndicator color="#fff" />',
            "          : <Text style={styles.uploadText}>",
            "              Post ({progress}%)",
            '            </Text>',
            '        }',
            '      </TouchableOpacity>',
            '    </View>',
            '  );',
            '}',
            '',
            'const styles = StyleSheet.create({',
            "  container:   { flex: 1, padding: 20, backgroundColor: '#000' },",
            "  pickBtn:     { padding: 16, backgroundColor: '#1E90FF',",
            "                 borderRadius: 10, alignItems: 'center', marginBottom: 16 },",
            "  pickText:    { color: '#fff', fontWeight: '700', fontSize: 16 },",
            "  input:       { backgroundColor: '#1a1a1a', color: '#fff', padding: 12,",
            "                 borderRadius: 10, marginBottom: 16, minHeight: 80 },",
            "  progressBar: { height: 6, backgroundColor: '#333', borderRadius: 3,",
            "                 marginBottom: 16, overflow: 'hidden' },",
            "  progressFill:{ height: '100%', backgroundColor: '#1E90FF',",
            "                 borderRadius: 3 },",
            "  uploadBtn:   { padding: 16, backgroundColor: '#2EA44F',",
            "                 borderRadius: 10, alignItems: 'center' },",
            "  disabled:    { opacity: 0.5 },",
            "  uploadText:  { color: '#fff', fontWeight: '700', fontSize: 16 },",
            '});',
        ]),
    ]))
    elems.append(PageBreak())

    # ── PRIORITY SUMMARY ─────────────────────────────────────────────────────
    elems += priority_table()
    elems.append(spacer(20))

    # ── QUICK REFERENCE TABLE ────────────────────────────────────────────────
    elems.append(Paragraph('FILES CHANGED — QUICK REFERENCE', ParagraphStyle('QR',
        fontName='Helvetica-Bold', fontSize=11, textColor=WHITE, spaceAfter=8)))
    hr(BORDER)

    data = [
        [Paragraph('<b>File</b>', S['body']),
         Paragraph('<b>Step(s)</b>', S['body']),
         Paragraph('<b>What Changes</b>', S['body'])],
        [Paragraph('shorts/views.py', ParagraphStyle('F', fontName='Courier', fontSize=8, textColor=ORANGE)),
         Paragraph('1, 2, 3, 4, 7', S['body']),
         Paragraph('Upload view, compression, thumbnail, pagination, streaming auth', S['body'])],
        [Paragraph('shorts/feed_algorithm.py', ParagraphStyle('F', fontName='Courier', fontSize=8, textColor=ORANGE)),
         Paragraph('5', S['body']),
         Paragraph('Add select_related + prefetch_related to base queryset', S['body'])],
        [Paragraph('shorts/serializers.py', ParagraphStyle('F', fontName='Courier', fontSize=8, textColor=ORANGE)),
         Paragraph('5', S['body']),
         Paragraph('Fix get_is_liked to use prefetch cache', S['body'])],
        [Paragraph('shorts/urls.py', ParagraphStyle('F', fontName='Courier', fontSize=8, textColor=ORANGE)),
         Paragraph('1', S['body']),
         Paragraph("Add 'shorts/upload/' URL pattern", S['body'])],
        [Paragraph('connectdial/settings.py', ParagraphStyle('F', fontName='Courier', fontSize=8, textColor=ORANGE)),
         Paragraph('6', S['body']),
         Paragraph('Add CACHES block pointing to Redis', S['body'])],
        [Paragraph('src/screens/ShortsScreen.jsx', ParagraphStyle('F', fontName='Courier', fontSize=8, textColor=ORANGE)),
         Paragraph('8, 9', S['body']),
         Paragraph('getItemLayout, windowSize, PAGE_SIZE, nextItem preload', S['body'])],
        [Paragraph('src/screens/PostScreen.jsx', ParagraphStyle('F', fontName='Courier', fontSize=8, textColor=ORANGE)),
         Paragraph('10', S['body']),
         Paragraph('CREATE NEW — upload UI with progress bar', S['body'])],
    ]
    t = Table(data, colWidths=[48*mm, 22*mm, 85*mm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), BLUE),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [CARD_BG, DARK_BG]),
        ('FONTSIZE', (0,0), (-1,-1), 8),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
        ('BOX', (0,0), (-1,-1), 0.5, BORDER),
        ('INNERGRID', (0,0), (-1,-1), 0.3, BORDER),
        ('ROUNDEDCORNERS', [4]),
    ]))
    elems.append(t)
    elems.append(spacer(20))

    # ── INSTALL COMMANDS ─────────────────────────────────────────────────────
    elems.append(Paragraph('INSTALL COMMANDS', ParagraphStyle('IC',
        fontName='Helvetica-Bold', fontSize=11, textColor=WHITE, spaceAfter=8)))
    hr(BORDER)
    elems.append(code_block([
        '# Backend (run in your Django project root)',
        'pip install django-redis',
        'sudo apt-get install ffmpeg          # Ubuntu / WSL',
        '# Windows: download from https://ffmpeg.org/download.html',
        '',
        '# Frontend (run in your React Native project root)',
        'npm install expo-image-picker        # or yarn add expo-image-picker',
        '',
        '# Start Redis (Ubuntu/WSL)',
        'sudo service redis-server start',
        'redis-cli ping                       # should return PONG',
    ]))

    return elems

# ── Page template ─────────────────────────────────────────────────────────────
def on_page(canvas, doc):
    canvas.saveState()
    # Dark background strip at top
    canvas.setFillColor(DARK_BG)
    canvas.rect(0, H - 18*mm, W, 18*mm, fill=1, stroke=0)
    # Header text
    canvas.setFont('Helvetica-Bold', 9)
    canvas.setFillColor(BLUE_LIGHT)
    canvas.drawString(15*mm, H - 12*mm, 'ConnectDial — Short Video Optimization Guide')
    canvas.setFont('Helvetica', 8)
    canvas.setFillColor(TEXT_SUB)
    canvas.drawRightString(W - 15*mm, H - 12*mm, f'Titus Tech Services · Page {doc.page}')
    # Bottom bar
    canvas.setFillColor(DARK_BG)
    canvas.rect(0, 0, W, 10*mm, fill=1, stroke=0)
    canvas.setFont('Helvetica', 7)
    canvas.setFillColor(TEXT_SUB)
    canvas.drawCentredString(W/2, 4*mm, 'ConnectDial · Confidential · May 2026')
    canvas.restoreState()

# ── Build ─────────────────────────────────────────────────────────────────────
OUT = '/mnt/user-data/outputs/ConnectDial_Shorts_Optimization_Guide.pdf'

doc = SimpleDocTemplate(
    OUT, pagesize=A4,
    leftMargin=20*mm, rightMargin=20*mm,
    topMargin=22*mm, bottomMargin=14*mm,
)

story = []
story += cover_page()
story += all_steps()

doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
print(f'PDF written → {OUT}')