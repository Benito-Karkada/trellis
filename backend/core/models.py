from django.conf import settings
from django.db import models
from django.utils import timezone
from django.core.validators import MinValueValidator

class LoginThrottle(models.Model):
    """Bounded, shared login counters; no email addresses or IPs are stored."""
    bucket = models.CharField(max_length=40, primary_key=True)
    window = models.BigIntegerField()
    attempts = models.PositiveIntegerField(default=0)


class Course(models.Model):
    metadata = models.JSONField(default=dict)
    title = models.CharField(max_length=200)
    term = models.CharField(max_length=40)
    canvas_context_id = models.CharField(max_length=255, blank=True)
    lti_registration = models.ForeignKey("LTIRegistration", null=True, blank=True, on_delete=models.PROTECT)
    def __str__(self): return self.title

class Membership(models.Model):
    external_ids = models.JSONField(default=dict)
    canvas_user_id = models.CharField(max_length=32, blank=True)
    class Role(models.TextChoices):
        STUDENT = "student"
        TA = "ta"
        HEAD_TA = "head_ta"
        INSTRUCTOR = "instructor"
    course = models.ForeignKey(Course, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    role = models.CharField(max_length=20, choices=Role.choices)
    active = models.BooleanField(default=True)
    source = models.CharField(max_length=20, default="manual")
    class Meta:
        constraints = [models.UniqueConstraint(fields=["course", "user"], name="unique_membership")]


class DiscussionThread(models.Model):
    class Kind(models.TextChoices):
        QUESTION = "question", "Question"
        NOTE = "note", "Note"
        POLL = "poll", "Poll"

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="discussion_threads")
    author = models.ForeignKey(Membership, null=True, on_delete=models.SET_NULL)
    author_label = models.CharField(max_length=150, blank=True)
    title = models.CharField(max_length=160)
    body = models.TextField(max_length=10000)
    editor_mode = models.CharField(max_length=12, choices=[("formatted", "Formatted"), ("plain", "Plain text"), ("markdown", "Markdown")], default="formatted")
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.QUESTION)
    visibility = models.CharField(max_length=12, choices=[("public", "Class"), ("private", "Instructors")], default="public")
    anonymous = models.CharField(max_length=12, choices=[("none", "Named"), ("classmates", "Anonymous to classmates"), ("everyone", "Anonymous to everyone")], default="none")
    pinned = models.BooleanField(default=False)
    reading_list = models.BooleanField(default=False)
    required_reading = models.BooleanField(default=False)
    locked = models.BooleanField(default=False)
    endorsed = models.BooleanField(default=False)
    history_hidden = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    folders = models.ManyToManyField("DiscussionFolder", blank=True, related_name="threads")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["course", "-updated_at"], name="discussion_recent_idx")]


class DiscussionReply(models.Model):
    thread = models.ForeignKey(DiscussionThread, on_delete=models.CASCADE, related_name="replies")
    author = models.ForeignKey(Membership, null=True, on_delete=models.SET_NULL)
    author_label = models.CharField(max_length=150, blank=True)
    body = models.TextField(max_length=10000)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.CASCADE, related_name="comments")
    resolved = models.BooleanField(default=False)
    anonymous = models.CharField(max_length=12, choices=[("none", "Named"), ("classmates", "Anonymous to classmates"), ("everyone", "Anonymous to everyone")], default="none")
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class DiscussionBoardSettings(models.Model):
    course = models.OneToOneField(Course, on_delete=models.CASCADE, related_name="discussion_settings")
    allow_student_posts = models.BooleanField(default=True)
    allow_student_notes = models.BooleanField(default=True)
    allow_student_polls = models.BooleanField(default=True)
    allow_anonymous = models.BooleanField(default=True)
    allow_anonymous_to_staff = models.BooleanField(default=False)
    allow_private = models.BooleanField(default=True)
    allow_student_answers = models.BooleanField(default=True)
    require_folder = models.BooleanField(default=False)
    reading_list_enabled = models.BooleanField(default=True)
    require_reading_before_posting = models.BooleanField(default=False)


class DiscussionDraft(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE)
    author = models.ForeignKey(Membership, on_delete=models.CASCADE)
    title = models.CharField(max_length=160, blank=True)
    body = models.TextField(max_length=10000, blank=True)
    editor_mode = models.CharField(max_length=12, default="formatted")
    kind = models.CharField(max_length=12, choices=DiscussionThread.Kind.choices, default=DiscussionThread.Kind.QUESTION)
    visibility = models.CharField(max_length=12, default="public")
    anonymous = models.CharField(max_length=12, default="none")
    folder_ids = models.JSONField(default=list)
    options = models.JSONField(default=list)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["course", "author"], name="unique_discussion_draft")]


class DiscussionFolder(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="discussion_folders")
    name = models.CharField(max_length=60)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["course", "name"], name="unique_discussion_folder")]
        ordering = ["position", "id"]


class DiscussionAnswer(models.Model):
    thread = models.ForeignKey(DiscussionThread, on_delete=models.CASCADE, related_name="answers")
    kind = models.CharField(max_length=12, choices=[("student", "Students"), ("instructor", "Instructors")])
    body = models.TextField(max_length=10000)
    last_editor = models.ForeignKey(Membership, null=True, on_delete=models.SET_NULL)
    last_editor_label = models.CharField(max_length=150, blank=True)
    endorsed = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["thread", "kind"], name="unique_discussion_answer_kind")]


class DiscussionSearchDocument(models.Model):
    """One searchable unit from a discussion thread.

    Embeddings are stored as their pgvector literal so the same migration and
    model also work in the SQLite test environment. PostgreSQL casts this value
    to vector for cosine ordering; SQLite uses the exact Python fallback.
    """
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="discussion_search_documents")
    thread = models.ForeignKey(DiscussionThread, on_delete=models.CASCADE, related_name="search_documents")
    content_type = models.CharField(max_length=12, choices=[("post", "Post"), ("answer", "Answer"), ("followup", "Followup")])
    object_id = models.PositiveBigIntegerField()
    source_label = models.CharField(max_length=40)
    content = models.TextField(max_length=20200)
    embedding = models.TextField()
    content_hash = models.CharField(max_length=64)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["thread", "content_type", "object_id"], name="unique_discussion_search_document")]
        indexes = [
            models.Index(fields=["course", "thread"], name="discussion_search_course_idx"),
            models.Index(fields=["content_type", "object_id"], name="discussion_search_object_idx"),
        ]


class DiscussionPostRevision(models.Model):
    thread = models.ForeignKey(DiscussionThread, on_delete=models.CASCADE, related_name="revisions")
    version = models.PositiveIntegerField()
    title = models.CharField(max_length=160)
    body = models.TextField(max_length=10000)
    editor_mode = models.CharField(max_length=12, default="formatted")
    editor_label = models.CharField(max_length=150)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["thread", "version"], name="unique_discussion_post_revision")]


class DiscussionAttachment(models.Model):
    thread = models.ForeignKey(DiscussionThread, on_delete=models.CASCADE, related_name="attachments")
    reply = models.ForeignKey(DiscussionReply, null=True, blank=True, on_delete=models.CASCADE, related_name="attachments")
    uploader = models.ForeignKey(Membership, null=True, on_delete=models.SET_NULL)
    name = models.CharField(max_length=120)
    blob = models.FileField(upload_to="discussion-attachments/%Y/%m/")
    size = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    deleted_at = models.DateTimeField(null=True, blank=True)


class DiscussionThreadState(models.Model):
    thread = models.ForeignKey(DiscussionThread, on_delete=models.CASCADE, related_name="member_states")
    membership = models.ForeignKey(Membership, on_delete=models.CASCADE)
    read_at = models.DateTimeField(null=True, blank=True)
    bookmarked = models.BooleanField(default=False)
    following = models.BooleanField(default=False)
    archived = models.BooleanField(default=False)
    liked = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["thread", "membership"], name="unique_discussion_thread_state")]


class DiscussionReplyLike(models.Model):
    reply = models.ForeignKey(DiscussionReply, on_delete=models.CASCADE, related_name="likes")
    membership = models.ForeignKey(Membership, on_delete=models.CASCADE)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["reply", "membership"], name="unique_discussion_reply_like")]


class DiscussionPollOption(models.Model):
    thread = models.ForeignKey(DiscussionThread, on_delete=models.CASCADE, related_name="poll_options")
    label = models.CharField(max_length=240)
    position = models.PositiveIntegerField(default=0)


class DiscussionPollVote(models.Model):
    thread = models.ForeignKey(DiscussionThread, on_delete=models.CASCADE, related_name="poll_votes")
    option = models.ForeignKey(DiscussionPollOption, on_delete=models.CASCADE, related_name="votes")
    membership = models.ForeignKey(Membership, on_delete=models.CASCADE)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["thread", "membership"], name="unique_discussion_poll_vote")]

class LTIRegistration(models.Model):
    issuer = models.URLField()
    client_id = models.CharField(max_length=255)
    deployment_id = models.CharField(max_length=255)
    jwks_url = models.URLField()
    token_url = models.URLField()
    key_id = models.CharField(max_length=255, blank=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["issuer", "client_id", "deployment_id"], name="unique_lti_registration")]

class LTIIdentity(models.Model):
    registration = models.ForeignKey(LTIRegistration, on_delete=models.PROTECT)
    subject = models.CharField(max_length=255)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["registration", "subject"], name="unique_lti_subject")]

class CanvasResourceLink(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE)
    activity = models.ForeignKey("Activity", on_delete=models.PROTECT, related_name="canvas_links")
    resource_link_id = models.CharField(max_length=255)
    line_item_url = models.URLField(blank=True)
    nrps_memberships_url = models.URLField(blank=True)
    ags_scopes = models.JSONField(default=list)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["course", "resource_link_id"], name="unique_canvas_resource_link")]

class Lesson(models.Model):
    class Visibility(models.TextChoices):
        STUDENT = "student", "Students and staff"
        STAFF = "staff", "Staff only"
    course = models.ForeignKey(Course, on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    position = models.PositiveIntegerField(default=0)
    deleted_at = models.DateTimeField(null=True, blank=True)
    source_path = models.CharField(max_length=1000, blank=True)
    visibility = models.CharField(max_length=12, choices=Visibility.choices, default=Visibility.STUDENT)
    metadata = models.JSONField(default=dict)

class Activity(models.Model):
    lesson = models.ForeignKey(Lesson, on_delete=models.PROTECT)
    title = models.CharField(max_length=200)
    position = models.PositiveIntegerField(default=0)
    deleted_at = models.DateTimeField(null=True, blank=True)
    published_revision = models.ForeignKey("Revision", null=True, blank=True, on_delete=models.PROTECT, related_name="published_by")
    metadata = models.JSONField(default=dict)

class Revision(models.Model):
    activity = models.ForeignKey(Activity, on_delete=models.CASCADE, related_name="revisions")
    number = models.PositiveIntegerField()
    content = models.JSONField(default=dict)
    grading = models.JSONField(default=dict)  # Private: never included in a student projection.
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["activity", "number"], name="unique_revision")]

class ActivityFile(models.Model):
    revision = models.ForeignKey(Revision, on_delete=models.CASCADE, related_name="files")
    path = models.CharField(max_length=500)
    visibility = models.CharField(max_length=20, choices=[("student", "Student"), ("staff", "Staff"), ("grader", "Grader"), ("quarantine", "Unclassified")], default="quarantine")
    blob = models.FileField(upload_to="activity-files/%Y/%m/")
    sha256 = models.CharField(max_length=64)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["revision", "path"], name="unique_revision_path")]

class Accommodation(models.Model):
    membership = models.ForeignKey(Membership, on_delete=models.CASCADE)
    activity = models.ForeignKey(Activity, null=True, blank=True, on_delete=models.CASCADE)
    lesson = models.ForeignKey(Lesson, null=True, blank=True, on_delete=models.CASCADE)
    time_multiplier = models.DecimalField(max_digits=5, decimal_places=2, default=1, validators=[MinValueValidator(1)])
    extra_minutes = models.PositiveIntegerField(default=0)
    due_at_override = models.DateTimeField(null=True, blank=True)
    extra_attempts = models.PositiveIntegerField(default=0)
    class Meta:
        constraints = [
            models.CheckConstraint(condition=~(models.Q(activity__isnull=False) & models.Q(lesson__isnull=False)), name="one_accommodation_scope"),
            models.UniqueConstraint(fields=["membership", "activity"], condition=models.Q(activity__isnull=False), name="unique_activity_accommodation"),
            models.UniqueConstraint(fields=["membership", "lesson"], condition=models.Q(lesson__isnull=False), name="unique_lesson_accommodation"),
            models.UniqueConstraint(fields=["membership"], condition=models.Q(activity__isnull=True, lesson__isnull=True), name="unique_course_accommodation"),
        ]


class QuizAttempt(models.Model):
    membership = models.ForeignKey(Membership, on_delete=models.CASCADE)
    lesson = models.ForeignKey(Lesson, on_delete=models.PROTECT)
    started_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["membership", "lesson"], name="unique_quiz_attempt")]

class QuizAccessConfig(models.Model):
    """Exam secrets never live in content metadata or student projections."""
    lesson = models.OneToOneField(Lesson, on_delete=models.CASCADE, related_name='access_config')
    enabled = models.BooleanField(default=False)
    password_hash = models.CharField(max_length=256, blank=True)
    version = models.CharField(max_length=64)


class QuizUnlockFailure(models.Model):
    membership = models.ForeignKey(Membership, on_delete=models.CASCADE)
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE)
    failures = models.PositiveIntegerField(default=0)
    window_started_at = models.DateTimeField(default=timezone.now)
    locked_until = models.DateTimeField(null=True, blank=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['membership', 'lesson'], name='unique_quiz_unlock_failure')]



class Submission(models.Model):
    received_at = models.DateTimeField(null=True, blank=True)
    revision = models.ForeignKey(Revision, on_delete=models.PROTECT)
    membership = models.ForeignKey(Membership, on_delete=models.PROTECT)
    response = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    is_preview = models.BooleanField(default=False)

class QuestionCooldown(models.Model):
    membership = models.ForeignKey(Membership, on_delete=models.CASCADE)
    revision = models.ForeignKey(Revision, on_delete=models.CASCADE)
    question_id = models.CharField(max_length=64)
    locked_until = models.DateTimeField()
    class Meta:
        constraints = [models.UniqueConstraint(fields=["membership", "revision", "question_id"], name="unique_question_cooldown")]

class GradeEvent(models.Model):
    submission = models.ForeignKey(Submission, on_delete=models.PROTECT)
    idempotency_key = models.UUIDField(unique=True)
    score = models.DecimalField(max_digits=10, decimal_places=4)
    maximum = models.DecimalField(max_digits=10, decimal_places=4)
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, default="pending")
    attempts = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)

class Workspace(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    revision = models.ForeignKey(Revision, on_delete=models.PROTECT)
    files = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)
    generation = models.PositiveIntegerField(default=0)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'revision'], name='unique_workspace')]


class CourseAsset(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE)
    source_path = models.CharField(max_length=1000)
    blob = models.FileField(upload_to="course-assets/")
    content_type = models.CharField(max_length=100)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["course", "source_path"], name="unique_course_asset")]


class ActivityProgress(models.Model):
    question_state = models.JSONField(default=dict)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    activity = models.ForeignKey(Activity, on_delete=models.CASCADE)
    viewed = models.BooleanField(default=False)
    completed = models.BooleanField(default=False)
    score = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    maximum = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "activity"], name="unique_activity_progress")]


class ExecutionJob(models.Model):
    review_signals = models.JSONField(default=dict, db_default={})
    import uuid
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    revision = models.ForeignKey(Revision, on_delete=models.PROTECT)
    generation = models.PositiveIntegerField()
    operation = models.CharField(max_length=10)
    snapshot = models.JSONField()
    entrypoint = models.CharField(max_length=500)
    status = models.CharField(max_length=20, default="pending")
    lease = models.CharField(max_length=64, blank=True)
    result = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    claimed_at = models.DateTimeField(null=True)
    preview = models.BooleanField(default=False)


class CanvasGradeUpdate(models.Model):
    include_comment = models.BooleanField(default=False, db_default=False)
    membership = models.ForeignKey(Membership,on_delete=models.CASCADE)
    lesson = models.ForeignKey(Lesson,on_delete=models.CASCADE)
    assignment_id = models.CharField(max_length=32)
    score = models.DecimalField(max_digits=12,decimal_places=4)
    maximum = models.DecimalField(max_digits=12,decimal_places=4)
    status = models.CharField(max_length=16,default='pending')
    attempts = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True,blank=True)
    last_error = models.CharField(max_length=200,blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['membership','lesson'],name='unique_canvas_grade_update')]


class APIToken(models.Model):
    import uuid
    id = models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    membership = models.ForeignKey(Membership,on_delete=models.CASCADE)
    name = models.CharField(max_length=120)
    secret_hash = models.CharField(max_length=64)
    scopes = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    last_used_at = models.DateTimeField(null=True,blank=True)
    revoked_at = models.DateTimeField(null=True,blank=True)


class APIAuditEvent(models.Model):
    course = models.ForeignKey(Course,on_delete=models.CASCADE)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL,null=True,on_delete=models.SET_NULL)
    token = models.ForeignKey(APIToken,null=True,on_delete=models.SET_NULL)
    request_id = models.UUIDField()
    method = models.CharField(max_length=8)
    path = models.CharField(max_length=1000)
    status = models.PositiveIntegerField()
    summary = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        indexes=[models.Index(fields=['course','created_at'],name='api_audit_course_time')]


class APIReplay(models.Model):
    token = models.ForeignKey(APIToken,on_delete=models.CASCADE)
    key = models.CharField(max_length=100)
    request_hash = models.CharField(max_length=64)
    response = models.JSONField(default=dict)
    response_status = models.PositiveIntegerField(default=0)
    response_etag = models.CharField(max_length=80,blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['token','key'],name='unique_api_replay_key')]


class AssignmentVisit(models.Model):
    membership = models.ForeignKey(Membership,on_delete=models.CASCADE)
    assignment = models.ForeignKey(Lesson,on_delete=models.CASCADE)
    first_opened_at = models.DateTimeField(auto_now_add=True)
    last_opened_at = models.DateTimeField()
    open_count = models.PositiveIntegerField(default=0)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['membership','assignment'],name='unique_assignment_visit')]


class LearningEvent(models.Model):
    membership = models.ForeignKey(Membership,on_delete=models.CASCADE)
    assignment = models.ForeignKey(Lesson,on_delete=models.CASCADE)
    part = models.ForeignKey(Activity,null=True,blank=True,on_delete=models.SET_NULL)
    kind = models.CharField(max_length=40)
    metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        indexes=[models.Index(fields=['membership','created_at'],name='learning_member_time'),
            models.Index(fields=['assignment','kind','created_at'],name='learning_assignment_kind')]


class StudentReview(models.Model):
    membership = models.OneToOneField(Membership, on_delete=models.CASCADE)
    status = models.CharField(max_length=20, default='unreviewed')
    notes = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    snapshot = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)


class VisualizationJob(models.Model):
    """Separate from graded jobs: replaying a trace never changes progress."""
    import uuid
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    revision = models.ForeignKey(Revision, null=True, blank=True, on_delete=models.CASCADE)
    source = models.TextField()
    files = models.JSONField(default=dict)
    stdin = models.TextField(blank=True)
    status = models.CharField(max_length=20, default="pending", db_index=True)
    lease = models.CharField(max_length=64, blank=True)
    result = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    claimed_at = models.DateTimeField(null=True)
    completed_at = models.DateTimeField(null=True)


class AssignmentChecklist(models.Model):
    """Personal reminders, independent of grades and isolated from staff preview."""
    membership = models.ForeignKey(Membership, on_delete=models.CASCADE)
    assignment = models.ForeignKey(Lesson, on_delete=models.CASCADE)
    student_view = models.BooleanField(default=False)
    checked = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['membership', 'assignment', 'student_view'],
            name='unique_assignment_checklist')]
