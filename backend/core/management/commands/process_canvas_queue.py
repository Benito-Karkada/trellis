import time
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from core.canvas_sync import process_one

class Command(BaseCommand):
    help='Deliver durable Canvas grade updates, retrying failures without student involvement.'
    def add_arguments(self,parser):parser.add_argument('--once',action='store_true')
    def handle(self,*args,**options):
        while True:
            close_old_connections()
            worked=process_one()
            if options['once']:return
            if not worked:time.sleep(2)
