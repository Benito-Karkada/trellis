from datetime import timedelta
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from core.models import Course, Membership, Lesson, QuizAttempt
from .test_studio import StudioTests


class MultiCourseTests(TestCase):
    def setUp(self):
        StudioTests.setUp(self)
        self.course = self.activity.lesson.course
        self.other = Course.objects.create(title='Environmental Science', term='Spring', metadata={'code': 'EAS 1600'})
        self.student_member = Membership.objects.create(user=self.staff, course=self.other, role='student')
        self.client.force_login(self.staff)

    def post(self, path, body, course=None):
        return self.client.post(path, body, content_type='application/json',
            **({'HTTP_X_TRELLIS_COURSE': str(course.pk)} if course else {}))

    def test_course_library_only_lists_active_memberships_and_hides_staff_counts(self):
        Course.objects.create(title='Private course', term='Secret')
        Lesson.objects.create(course=self.other, title='Hidden quiz', visibility='staff')
        Lesson.objects.create(course=self.other, title='Water quality')
        rows=self.client.get('/api/courses/').json()
        self.assertTrue(rows['can_create'])
        self.assertEqual(len(rows['courses']),2)
        other=next(c for c in rows['courses'] if c['id']==self.other.pk)
        self.assertEqual(other['section_count'],1)
        self.assertEqual(other['role'],'student')
        self.student_member.active=False;self.student_member.save()
        self.assertEqual(len(self.client.get('/api/courses/').json()['courses']),1)

    def test_course_context_selects_outline_without_session_crosstalk(self):
        for course in (self.other,self.course,self.other):
            response=self.client.get('/api/outline/',HTTP_X_TRELLIS_COURSE=str(course.pk))
            self.assertEqual(response.json()['id'],course.pk)
            self.assertEqual(response.json()['title'],course.title)

    def test_instructor_in_one_course_cannot_administer_selected_student_course(self):
        for path in ('/api/settings/roster/','/api/gradebook/','/api/structure/draft/',
                     '/api/settings/course-controls/','/api/settings/canvas/assignments/'):
            self.assertEqual(self.client.get(path,HTTP_X_TRELLIS_COURSE=str(self.other.pk)).status_code,403,path)
        self.assertEqual(self.post('/api/structure/lessons/',{'action':'create','title':'Wrong course'},self.other).status_code,403)
        self.assertFalse(Lesson.objects.filter(title='Wrong course').exists())

    def test_invalid_unenrolled_or_mismatched_context_never_falls_back(self):
        for value in ('0','nonsense','999999','²','9'*100):
            self.assertEqual(self.client.get('/api/outline/',HTTP_X_TRELLIS_COURSE=value).status_code,403)
        self.assertEqual(self.client.get(f'/api/studio/{self.activity.pk}/?mode=config',HTTP_X_TRELLIS_COURSE=str(self.other.pk)).status_code,403)

    def test_create_blank_course_grants_creator_only_instructor_membership(self):
        response=self.post('/api/courses/',{'title':'History of Art','code':'ART 101','term':'Spring','description':'Visual culture'})
        self.assertEqual(response.status_code,201)
        course=Course.objects.get(pk=response.json()['id'])
        self.assertFalse(course.lesson_set.exists())
        self.assertEqual(list(course.membership_set.values_list('user_id','role')),[(self.staff.pk,'instructor')])
        self.assertEqual(course.metadata['code'],'ART 101')

    def test_student_ta_and_student_preview_cannot_create_courses(self):
        for user in (self.student,):
            self.client.force_login(user)
            self.assertFalse(self.client.get('/api/courses/').json()['can_create'])
            self.assertEqual(self.post('/api/courses/',{'title':'No'}).status_code,403)
        self.client.force_login(self.staff)
        member=Membership.objects.get(user=self.staff,course=self.course);member.role='ta';member.save()
        self.assertEqual(self.post('/api/courses/',{'title':'No'}).status_code,403)
        member.role='instructor';member.save()
        self.post('/api/student-view/',{'enabled':True},self.course)
        self.assertEqual(self.post('/api/courses/',{'title':'No'}).status_code,403)

    def test_course_identity_is_instructor_only_and_scoped(self):
        values={'title':'New name','code':'EAS 1600','term':'Summer','description':'Explore water'}
        self.assertEqual(self.post('/api/settings/course/',values,self.other).status_code,403)
        self.assertEqual(self.post('/api/settings/course/',values,self.course).status_code,200)
        self.course.refresh_from_db();self.other.refresh_from_db()
        self.assertEqual(self.course.title,'New name');self.assertEqual(self.other.title,'Environmental Science')
        self.assertEqual(self.post('/api/settings/course/',{**values,'title':' '},self.course).status_code,400)

    def test_active_exam_prevents_switching_to_a_different_course(self):
        quiz=Lesson.objects.create(course=self.other,title='Exam',metadata={'kind':'programming_quiz','exam_mode':True})
        QuizAttempt.objects.create(membership=self.student_member,lesson=quiz,expires_at=timezone.now()+timedelta(minutes=5))
        self.assertEqual(self.client.get('/api/outline/',HTTP_X_TRELLIS_COURSE=str(self.course.pk)).status_code,403)

    def test_registration_does_not_enroll_in_arbitrary_first_course(self):
        self.client.logout()
        response=self.post('/api/auth/register/',{'email':'new@example.edu','password':'A useful long password 2991'})
        self.assertEqual(response.status_code,200)
        user=get_user_model().objects.get(email='new@example.edu')
        self.assertFalse(Membership.objects.filter(user=user).exists())
        self.assertEqual(self.client.get('/api/courses/').json(),{'courses':[],'can_create':False})
