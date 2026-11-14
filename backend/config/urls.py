from django.contrib import admin
from django.urls import path
from core.views import student_activity, preview_activity, health
from core import studio
from core import learning
from core import execution
from core import accounts
from core import course_settings
from core import quizzes
from core import structure
from core import gradebook
urlpatterns = [path("admin/", admin.site.urls), path("api/health/", health), path("api/activities/<int:pk>/", student_activity), path("api/activities/<int:pk>/preview/", preview_activity)]
urlpatterns += [path('api/session/', studio.session), path('api/local-login/', studio.local_login),
    path('api/student-view/',studio.student_view),
    path('api/outline/', studio.outline), path('api/studio/<int:pk>/', studio.detail),
    path('api/studio/<int:pk>/edit/', studio.edit), path('api/files/<int:pk>/', studio.file_text),
    path('api/workspaces/<int:pk>/', studio.save_workspace), path('api/check/<int:pk>/', studio.check_answer)]
urlpatterns += [path('api/assets/<int:pk>/',learning.asset),path('api/viewed/<int:pk>/',learning.viewed),
                path('api/submit-native/<int:pk>/',learning.submit_native)]
urlpatterns += [path('api/execute/<int:pk>/',execution.enqueue),path('api/jobs/<uuid:pk>/',execution.status),
    path('api/runner/claim/',execution.claim),path('api/runner/complete/<uuid:pk>/',execution.complete)]
urlpatterns += [path('api/auth/login/',accounts.sign_in),path('api/auth/register/',accounts.register),
    path('api/auth/logout/',accounts.sign_out),path('api/settings/roster/',course_settings.roster),
    path('api/settings/enrollments/',course_settings.add_enrollment),
    path('api/settings/enrollments/<int:pk>/login/',course_settings.provision_login),
    path('api/settings/enrollments/import/',course_settings.import_enrollments),
    path('api/settings/roster/sync/',course_settings.sync_canvas_roster),
    path('api/settings/accommodations/',course_settings.accommodation_data),
    path('api/settings/accommodations/save/',course_settings.save_accommodations)]
urlpatterns += [path('api/settings/quizzes/', quizzes.quiz_data),
    path('api/settings/quizzes/<int:pk>/', quizzes.save_quiz),
    path('api/settings/quizzes/<int:pk>/review/', quizzes.review),
    path('api/quizzes/<int:pk>/status/', quizzes.status),
    path('api/quizzes/<int:pk>/start/', quizzes.start),
    path('api/quizzes/<int:pk>/finish/', quizzes.finish)]
urlpatterns += [path('api/quizzes/<int:pk>/reset-test/', quizzes.reset_test_attempt)]
urlpatterns += [path('api/structure/draft/', structure.draft),
    path('api/structure/save/', structure.save_draft),
    path('api/structure/lessons/', structure.lessons),
    path('api/structure/activities/', structure.activities),
    path('api/gradebook/', gradebook.gradebook), path('api/gradebook/detail/', gradebook.detail)]

from core import course_controls,canvas_sync
urlpatterns += [path('api/settings/course-controls/',course_controls.data),
    path('api/settings/course-controls/save/',course_controls.save),
    path('api/gradebook/sync-canvas/',canvas_sync.sync_all)]

urlpatterns += [path('api/gradebook/work/',gradebook.work)]

from core import hints
urlpatterns += [path('api/hints/<int:pk>/',hints.reveal)]

from django.urls import include
from core import tracking,pace
from core.rest import tokens as rest_tokens
urlpatterns += [path('api/v1/',include('core.rest.urls')),
    path('api/settings/api-tokens/',rest_tokens.settings_tokens),
    path('api/settings/api-tokens/<uuid:token_id>/revoke/',rest_tokens.settings_tokens),
    path('api/assignments/<int:assignment_id>/open/',tracking.opened),
    path('api/assignments/<int:assignment_id>/pace/',pace.check)]

urlpatterns += [path("api/reset-native/<int:pk>/", learning.reset_native)]

urlpatterns += [path('api/settings/enrollments/<int:pk>/remove/',course_settings.remove_enrollment)]

from core import focus_tracking
urlpatterns += [path('api/assignments/<int:assignment_id>/focus/',focus_tracking.changed)]

from core import submission_review
urlpatterns += [path('api/settings/submission-review/',submission_review.report),path('api/settings/submission-review/policy/',submission_review.save_policy),path('api/settings/submission-review/<int:pk>/',submission_review.save_review)]

urlpatterns += [path('api/settings/submission-review/attempts/<uuid:job_id>/',submission_review.attempt)]

from core import review_export
urlpatterns += [path("api/settings/submission-review/export/",review_export.download)]

from core import ed_discussion
urlpatterns += [path("api/settings/ed-discussion/", ed_discussion.settings_data),
    path("api/settings/ed-discussion/save/", ed_discussion.settings_save)]

from core import honorlock
urlpatterns += [path("api/settings/quizzes/<int:pk>/honorlock/",honorlock.save_settings)]

from core import visualization
urlpatterns += [path("api/visualizations/", visualization.start),
    path("api/visualizations/<uuid:pk>/", visualization.status),
    path("api/visualizations/samples/<int:pk>/", visualization.sample_data)]

from core import courses, canvas_assignments
urlpatterns += [path('api/courses/', courses.collection),
    path('api/settings/course/', courses.settings_data),
    path('api/settings/canvas/assignments/', canvas_assignments.overview),
    path('api/settings/canvas/configure/', canvas_assignments.configure),
    path('api/settings/canvas/assignments/<int:pk>/publish/', canvas_assignments.publish_assignment)]

from core import discussions
urlpatterns += [path("api/discussions/", discussions.list_threads),
    path("api/discussions/meta/", discussions.meta),
    path("api/discussions/draft/", discussions.get_draft),
    path("api/discussions/draft/save/", discussions.save_draft),
    path("api/discussions/draft/discard/", discussions.discard_draft),
    path("api/discussions/settings/", discussions.save_settings),
    path("api/discussions/folders/", discussions.folders),
    path("api/discussions/statistics/", discussions.statistics),
    path("api/discussions/statistics/export/", discussions.statistics_export),
    path("api/discussions/new/", discussions.create_thread),
    path("api/discussions/<int:pk>/", discussions.read_thread),
    path("api/discussions/<int:pk>/replies/", discussions.create_reply),
    path("api/discussions/<int:pk>/answer/", discussions.save_answer),
    path("api/discussions/<int:pk>/answer/endorse/", discussions.endorse_answer),
    path("api/discussions/<int:pk>/action/", discussions.thread_action),
    path("api/discussions/<int:pk>/edit/", discussions.edit_thread),
    path("api/discussions/<int:pk>/history/", discussions.history),
    path("api/discussions/<int:pk>/delete/", discussions.delete_thread),
    path("api/discussions/<int:pk>/vote/", discussions.vote),
    path("api/discussions/<int:pk>/attachments/", discussions.upload_attachment),
    path("api/discussions/replies/<int:pk>/attachments/", discussions.upload_reply_attachment),
    path("api/discussions/attachments/<int:pk>/", discussions.download_attachment),
    path("api/discussions/attachments/<int:pk>/remove/", discussions.remove_attachment),
    path("api/discussions/replies/<int:pk>/action/", discussions.reply_action)]
