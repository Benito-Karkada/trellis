from unittest.mock import Mock, patch
import requests
from django.test import TestCase
from core.models import Course, Lesson, Membership, Revision
from .test_studio import StudioTests


@patch.dict('os.environ',{'CANVAS_API_TOKEN':'secret-token','CANVAS_BASE_URL':'https://canvas.example.edu'})
class CanvasAssignmentTests(TestCase):
    def setUp(self):
        StudioTests.setUp(self)
        self.course=self.activity.lesson.course
        self.course.canvas_context_id='123';self.course.metadata={'trellis_public_url':'https://trellis.example.edu'};self.course.save()
        self.lesson=self.activity.lesson
        self.lesson.title='Water & <Science>'
        self.lesson.metadata={'due_at':'2027-01-10T12:00:00+00:00'};self.lesson.save()
        self.revision.grading={'maximum_points':'2.5','questions':{'q':{'answers':['ok']}}};self.revision.save()
        self.client.force_login(self.staff)
        self.path=f'/api/settings/canvas/assignments/{self.lesson.pk}/publish/'

    def post(self,path,body):
        return self.client.post(path,body,content_type='application/json',HTTP_X_TRELLIS_COURSE=str(self.course.pk))

    @patch('core.canvas_assignments.requests.request')
    def test_create_payload_has_title_published_points_due_date_and_course_scoped_link(self,send):
        Revision.objects.create(activity=self.activity,number=2,created_by=self.staff,content=self.revision.content,grading={'maximum_points':'999','questions':{'secret':{}}})
        send.return_value=Mock(status_code=201,json=Mock(return_value={'id':456}))
        response=self.post(self.path,{'published':False})
        self.assertEqual(response.status_code,200)
        self.assertEqual(send.call_args.args,('POST','https://canvas.example.edu/api/v1/courses/123/assignments'))
        payload=send.call_args.kwargs['json']['assignment']
        self.assertEqual(payload['points_possible'],2.5)
        self.assertEqual(payload['name'],self.lesson.title)
        self.assertEqual(payload['due_at'],self.lesson.metadata['due_at'])
        self.assertEqual(payload['submission_types'],['none'])
        self.assertFalse(payload['published'])
        self.assertIn(f'course={self.course.pk}&amp;lesson={self.lesson.pk}',payload['description'])
        self.assertIn('Water &amp; &lt;Science&gt;',payload['description'])
        self.assertNotIn('secret',str(payload))
        self.assertFalse(send.call_args.kwargs['allow_redirects'])
        self.lesson.refresh_from_db();self.assertEqual(self.lesson.metadata['canvas_assignment_id'],'456')

    @patch('core.canvas_assignments.requests.request')
    def test_repeat_publish_updates_mapped_assignment_without_second_create(self,send):
        send.return_value=Mock(status_code=201,json=Mock(return_value={'id':456}))
        self.post(self.path,{})
        self.lesson.refresh_from_db();self.lesson.title='Updated title';self.lesson.save()
        send.return_value=Mock(status_code=200,json=Mock(return_value={'id':456}))
        response=self.post(self.path,{'published':True})
        self.assertEqual(response.json()['action'],'updated')
        self.assertEqual(send.call_args.args[0],'PUT')
        self.assertTrue(send.call_args.args[1].endswith('/456'))
        self.assertEqual(send.call_args.kwargs['json']['assignment']['name'],'Updated title')

    @patch('core.canvas_assignments.requests.request')
    def test_ambiguous_create_is_durable_and_never_blindly_retried(self,send):
        send.side_effect=requests.Timeout('secret-token must not be stored')
        self.assertEqual(self.post(self.path,{}).status_code,502)
        self.assertEqual(self.post(self.path,{}).status_code,409)
        self.assertEqual(send.call_count,1)
        self.lesson.refresh_from_db()
        self.assertEqual(self.lesson.metadata['canvas_publish']['status'],'uncertain')
        self.assertNotIn('secret-token',str(self.lesson.metadata))
        response=self.post('/api/settings/course-controls/save/',{'assignment_id':self.lesson.pk,'due_at':self.lesson.metadata['due_at'],'canvas_assignment_id':'777'})
        self.assertEqual(response.status_code,200)
        send.side_effect=None;send.return_value=Mock(status_code=200,json=Mock(return_value={'id':777}))
        self.assertEqual(self.post(self.path,{}).status_code,200)
        self.assertEqual(send.call_args.args[0],'PUT')

    @patch('core.canvas_assignments.requests.request')
    def test_duplicate_inflight_request_and_empty_section_are_rejected(self,send):
        self.lesson.metadata={**self.lesson.metadata,'canvas_publish':{'status':'publishing'}};self.lesson.save()
        self.assertEqual(self.post(self.path,{}).status_code,409)
        empty=Lesson.objects.create(course=self.course,title='Draft section')
        self.assertEqual(self.post(f'/api/settings/canvas/assignments/{empty.pk}/publish/',{}).status_code,409)
        send.assert_not_called()

    @patch('core.canvas_assignments.requests.request')
    def test_server_error_and_malformed_success_do_not_trigger_duplicate_create(self,send):
        for response in (Mock(status_code=500),Mock(status_code=201,json=Mock(return_value={'unexpected':True}))):
            self.lesson.metadata={};self.lesson.save()
            send.return_value=response
            self.assertEqual(self.post(self.path,{}).status_code,502)
            self.assertEqual(self.post(self.path,{}).status_code,409)
        self.assertEqual(send.call_count,2)

    @patch('core.canvas_assignments.requests.request')
    def test_rate_limit_can_be_retried_explicitly_and_does_not_save_response_body(self,send):
        send.return_value=Mock(status_code=429,text='sensitive remote response')
        self.assertEqual(self.post(self.path,{}).status_code,502)
        self.lesson.refresh_from_db();self.assertEqual(self.lesson.metadata['canvas_publish']['status'],'failed')
        self.assertNotIn('sensitive',str(self.lesson.metadata))

    @patch('core.canvas_assignments.requests.request')
    def test_students_tas_preview_and_other_courses_cannot_publish(self,send):
        self.client.force_login(self.student)
        self.assertEqual(self.post(self.path,{}).status_code,403)
        self.client.force_login(self.staff)
        member=Membership.objects.get(user=self.staff);member.role='ta';member.save()
        self.assertEqual(self.post(self.path,{}).status_code,403)
        member.role='instructor';member.save()
        other=Course.objects.create(title='Other',term='Term')
        lesson=Lesson.objects.create(course=other,title='Secret')
        self.assertEqual(self.post(f'/api/settings/canvas/assignments/{lesson.pk}/publish/',{}).status_code,404)
        self.post('/api/student-view/',{'enabled':True})
        self.assertEqual(self.post(self.path,{}).status_code,403)
        send.assert_not_called()

    def test_configuration_rejects_unsafe_links_and_mapping_retarget(self):
        path='/api/settings/canvas/configure/'
        for url in ('javascript:alert(1)','https://user:password@example.edu','http://example.edu','https://example.edu/?x=1'):
            self.assertEqual(self.post(path,{'canvas_course_id':'123','trellis_url':url}).status_code,400)
        self.assertEqual(self.post(path,{'canvas_course_id':'123','trellis_url':'http://localhost:5173'}).status_code,200)
        self.lesson.metadata={**self.lesson.metadata,'canvas_assignment_id':'456'};self.lesson.save()
        self.assertEqual(self.post(path,{'canvas_course_id':'999','trellis_url':'https://trellis.example.edu'}).status_code,409)
        self.assertEqual(self.post('/api/settings/course-controls/save/',{'canvas_course_id':'999'}).status_code,409)

    @patch.dict('os.environ',{'CANVAS_API_TOKEN':''})
    @patch('core.canvas_assignments.requests.request')
    def test_unconfigured_local_preview_never_makes_canvas_requests(self,send):
        data=self.client.get('/api/settings/canvas/assignments/',HTTP_X_TRELLIS_COURSE=str(self.course.pk)).json()
        self.assertFalse(data['configured']);self.assertEqual(data['assignments'][0]['points'],'2.5')
        self.assertEqual(self.post(self.path,{}).status_code,409)
        send.assert_not_called()
