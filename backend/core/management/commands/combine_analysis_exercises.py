from pathlib import Path
from django.core.management.base import BaseCommand,CommandError
from django.contrib.auth import get_user_model
from core.models import Lesson
from core.combine_analysis import combine_group


class Command(BaseCommand):
    help='Combine existing native assessment groups with their instructions, sandbox and dataset.'
    def add_arguments(self,parser):
        parser.add_argument('--lesson',type=int,required=True)
        parser.add_argument('--user',required=True)
        parser.add_argument('--dataset-root',type=Path,required=True)
        parser.add_argument('--group',action='append',required=True,help='GROUP TITLE=DATASET_FILENAME; repeatable')
    def handle(self,*args,**options):
        lesson=Lesson.objects.get(pk=options['lesson']);user=get_user_model().objects.get(username=options['user'])
        for value in options['group']:
            group,filename=value.rsplit('=',1);path=(options['dataset_root']/filename).resolve()
            if not path.is_relative_to(options['dataset_root'].resolve()):raise CommandError('Unsafe dataset path.')
            primary,changed=combine_group(lesson,group,filename,path.read_bytes(),user)
            self.stdout.write(f'{primary.pk}: {primary.title}: '+('combined' if changed else 'already combined'))
