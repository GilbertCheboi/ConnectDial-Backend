from django.contrib import admin
from .models import ShortVideo, VideoLike, VideoComment, CommentMention, VideoShare, VideoView
# Register your models here.

admin.site.register(ShortVideo)
admin.site.register(VideoLike)
admin.site.register(VideoComment)
admin.site.register(CommentMention)
admin.site.register(VideoShare)
admin.site.register(VideoView)
