from pathlib import Path
import hashlib
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from core.models import Course, Lesson, Activity, Revision, ActivityFile, Membership


class Command(BaseCommand):
    help = 'Seed the local studio with a real downloaded coding activity'
    def add_arguments(self, parser): parser.add_argument('--source', type=Path, required=True)
    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG: raise CommandError('Local development only')
        user, created = get_user_model().objects.get_or_create(username='studio-instructor', defaults={'first_name': 'Course', 'last_name': 'Staff'})
        if created: user.set_unusable_password(); user.save()
        course, _ = Course.objects.get_or_create(title='Introduction to Computing', term='CS 1301 · Development')
        Membership.objects.get_or_create(course=course, user=user, defaults={'role':'instructor'})
        lesson, _ = Lesson.objects.get_or_create(course=course, title='2.2 · Variables', defaults={'position': 0})
        activity, _ = Activity.objects.get_or_create(lesson=lesson, title='Days between dates', defaults={'position': 1})
        if not activity.published_revision_id:
            content = {'version':1,'blocks':[
                {'id':'intro','type':'paragraph','content':[{'type':'text','text':'Practice working with variables, dates, and arithmetic. Use the provided code to calculate the number of days between two dates.'}]},
                {'id':'task','type':'coding','prompt':[{'type':'text','text':'Calculate days_between using earlier_date and later_date. Keep the provided setup code intact. Your feedback will appear in full_results.txt after grading; a sample answer becomes available after a successful submission.'}]}]}
            rev, _ = Revision.objects.get_or_create(activity=activity, number=1, defaults={'created_by':user, 'content':content, 'grading':{'runtime':'python','legacy_part':'5591043'}})
            for folder, visibility in [('startercode','student'),('private','grader'),('scripts','grader')]:
                for path in sorted((options['source']/folder).rglob('*')):
                    if not path.is_file() or '__pycache__' in path.parts: continue
                    raw=path.read_bytes()
                    name=str(path.relative_to(options['source']/folder))
                    ActivityFile.objects.create(revision=rev,path=name if visibility=='student' else folder+'/'+name,
                        visibility='staff' if folder=='private' and name.startswith('sample_answer') else visibility,
                        blob=ContentFile(raw,name=path.name),sha256=hashlib.sha256(raw).hexdigest())
            activity.published_revision=rev; activity.save()
        reading,_=Activity.objects.get_or_create(lesson=lesson,title='A name for a value',defaults={'position':0})
        if not reading.revisions.exists():
            rev=Revision.objects.create(activity=reading,number=1,created_by=user,content={'version':1,'blocks':[
                {'id':'intro','type':'paragraph','content':[{'type':'text','text':'A variable gives a value a name. Once you assign that name, you can use it throughout your program.'}]},
                {'id':'example','type':'code','language':'python','text':'course = "CS 1301"\nstudents = 125\nprint(course, students)'},
                {'id':'question','type':'multiple_choice','prompt':[{'type':'text','text':'What value does students hold after this code runs?'}],'choices':[{'id':'a','content':[{'type':'text','text':'125'}]},{'id':'b','content':[{'type':'text','text':'CS 1301'}]},{'id':'c','content':[{'type':'text','text':'students'}]}]}]},grading={'questions':{'question':{'correct_choice_ids':['a']}}})
            reading.published_revision=rev; reading.save()
        self.stdout.write('Studio ready. Sign in with the local development button.')
