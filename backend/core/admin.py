from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User,Course,Membership,Folder,Resource,Assignment,Submission,Announcement
admin.site.register(User,UserAdmin)
for model in [Course,Membership,Folder,Resource,Assignment,Submission,Announcement]: admin.site.register(model)
admin.site.site_header='Academia Share administration'

from .models import Exam,ExamAttempt,VideoCall
admin.site.register([Exam,ExamAttempt,VideoCall])
