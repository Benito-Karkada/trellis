from django.urls import path
from . import content,records,execution,documentation
urlpatterns=[
 path('courses/<int:course_id>/parts/titles/',content.part_titles),
 path('courses/',content.courses),path('courses/<int:course_id>/',content.course_detail),
 path('courses/<int:course_id>/assignments/',content.assignments),path('assignments/<int:assignment_id>/',content.assignment_detail),
 path('assignments/<int:assignment_id>/parts/',content.parts),path('parts/<int:part_id>/',content.part_detail),
 path('parts/<int:part_id>/revisions/',content.revisions),path('parts/<int:part_id>/revisions/<int:revision_id>/',content.revision_detail),
 path('parts/<int:part_id>/publish/',content.publish_part),path('parts/<int:part_id>/files/',content.files),
 path('parts/<int:part_id>/files/<path:file_path>',content.file_detail),path('parts/<int:part_id>/grader/',content.grader),
 path('courses/<int:course_id>/reports/missing-graders/',content.missing_graders),
 path('courses/<int:course_id>/enrollments/',records.enrollments),path('enrollments/<int:enrollment_id>/',records.enrollment_detail),
 path('enrollments/<int:enrollment_id>/accommodations/',records.accommodations),
 path('enrollments/<int:enrollment_id>/workspaces/<int:part_id>/',records.workspace),
 path('courses/<int:course_id>/grades/',records.grades),path('courses/<int:course_id>/submissions/',records.submissions),
 path('courses/<int:course_id>/execution-jobs/',records.execution_jobs),
 path('courses/<int:course_id>/visits/',records.visits),path('courses/<int:course_id>/events/',records.events),
 path('courses/<int:course_id>/audit-events/',records.audit),
 path('parts/<int:part_id>/test-runs/',execution.test_runs),path('test-runs/<uuid:job_id>/',execution.test_run_detail),
 path('courses/<int:course_id>/reports/submission-review/',records.submission_review_report),
 path('courses/<int:course_id>/reports/submission-review/export/',records.submission_review_export),
 path('openapi.json',documentation.openapi),path('docs/',documentation.guide),
]
