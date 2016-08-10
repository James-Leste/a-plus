import datetime
import hashlib
import hmac

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
from django.core.urlresolvers import reverse
from django.core.validators import RegexValidator
from django.db import models
from django.db.models.signals import post_delete
from django.template import loader, Context
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.translation import ugettext_lazy as _

from course.models import CourseModule, LearningObjectCategory
from external_services.lti import LTIRequest
from external_services.models import LTIService
from inheritance.models import ModelWithInheritance
from lib.fields import JSONField
from lib.helpers import update_url_params, has_same_domain, safe_file_name, roman_numeral
from lib.models import UrlMixin
from userprofile.models import UserProfile

from .protocol.aplus import load_exercise_page, load_feedback_page
from .protocol.exercise_page import ExercisePage


class LearningObjectManager(models.Manager):

    def get_queryset(self):
        return super().get_queryset()\
            .defer('description', 'content', 'content_head')\
            .select_related('course_module', 'course_module__course_instance',
                'course_module__course_instance__course', 'category')

    def find_enrollment_exercise(self, course_instance):
        return self.filter(
            course_module__course_instance=course_instance,
            status='enrollment'
        ).first()


class LearningObject(UrlMixin, ModelWithInheritance):
    """
    All learning objects inherit this model.
    """
    STATUS_READY = 'ready'
    STATUS_UNLISTED = 'unlisted'
    STATUS_ENROLLMENT = 'enrollment'
    STATUS_HIDDEN = 'hidden'
    STATUS_MAINTENANCE = 'maintenance'
    STATUS_CHOICES = (
        (STATUS_READY, _("Ready")),
        (STATUS_UNLISTED, _("Unlisted in table of contents")),
        (STATUS_ENROLLMENT, _("Enrollment questions")),
        (STATUS_HIDDEN, _("Hidden from non course staff")),
        (STATUS_MAINTENANCE, _("Maintenance")),
    )
    status = models.CharField(max_length=32,
        choices=STATUS_CHOICES, default=STATUS_READY)
    category = models.ForeignKey(LearningObjectCategory, related_name="learning_objects")
    course_module = models.ForeignKey(CourseModule, related_name="learning_objects")
    parent = models.ForeignKey('self', blank=True, null=True, related_name='children')
    order = models.IntegerField(default=1)
    url = models.CharField(max_length=255,
        validators=[RegexValidator(regex="^[\w\-\.]*$")],
        help_text=_("Input an URL identifier for this object."))
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True,
        help_text=_("Internal description is not presented on site."))
    use_wide_column = models.BooleanField(default=False,
        help_text=_("Remove the third info column for more space."))

    service_url = models.URLField(blank=True)
    exercise_info = JSONField(blank=True)
    model_answers = models.TextField(blank=True)

    content = models.TextField(blank=True)
    content_head = models.TextField(blank=True)
    content_time = models.DateTimeField(blank=True, null=True)

    objects = LearningObjectManager()

    class Meta:
        app_label = "exercise"
        ordering = ['course_module', 'order', 'id']
        unique_together = ['course_module', 'parent', 'url']

    def clean(self):
        """
        Validates the model before saving (standard method used in Django admin).
        """
        course_instance_error = ValidationError({
            'category':_('Course_module and category must belong to the same course instance.')
        })
        try:
            if (self.course_module.course_instance != self.category.course_instance):
                raise course_instance_error
        except (LearningObjectCategory.DoesNotExist, CourseModule.DoesNotExist):
            raise course_instance_error
        if self.parent and (self.parent.course_module != self.course_module
                or self.parent.id == self.id):
            raise ValidationError({
                'parent':_('Cannot select parent from another course module.')
            })
        RESERVED = ("submissions", "plain", "info")
        if self.url in RESERVED:
            raise ValidationError({
                'url':_("Taken words include: {}").format(", ".join(RESERVED))
            })

    def __str__(self):
        if self.order >= 0:
            if self.course_instance.content_numbering == 1:
                number = self.number()
                if self.course_instance.module_numbering in [1,3]:
                    return "{:d}{} {}".format(self.course_module.order,
                        number, self.name)
                return "{} {}".format(number[1:], self.name)
            elif self.course_instance.content_numbering == 2:
                return "{} {}".format(roman_numeral(self.order), self.name)
        return self.name

    def number(self):
        parent = self.course_module._children().parent(self)
        if parent:
            return "{}.{:d}".format(parent.number(), self.order)
        return ".{:d}".format(self.order)

    @property
    def course_instance(self):
        return self.course_module.course_instance

    @property
    def is_submittable(self):
        return False

    def is_empty(self):
        return not self.service_url and self.as_leaf_class()._is_empty()

    def _is_empty(self):
        return True

    def is_open(self, when=None):
        return self.course_module.is_open(when=when)

    def is_after_open(self, when=None):
        return self.course_module.is_after_open(when=when)

    def next(self):
        return self.course_module._children().next(self)

    def previous(self):
        return self.course_module._children().previous(self)

    def flat_learning_objects(self, with_sub_markers=True):
        return self.course_module._children().flat(self, with_sub_markers)

    def parent_cached(self):
        return self.course_module._children().parent(self)

    def parent_list(self):
        parents = self.course_module._children().parents(self)
        return parents[:-1]

    def get_path_parts(self):
        return [n.url for n in self.course_module._children().parents(self)]

    def get_path(self):
        return '/'.join(self.get_path_parts())


    ABSOLUTE_URL_NAME = "exercise"

    def get_url_kwargs(self):
        return dict(exercise_path=self.get_path(), **self.course_module.get_url_kwargs())

    def get_submission_list_url(self):
        return self.get_url("submission-list")

    def get_load_url(self, request, students, url_name="exercise"):
        return self.service_url

    def load(self, request, students, url_name="exercise"):
        """
        Loads the learning object page.
        """
        if not self.service_url:
            return ExercisePage(self)

        # Archived course presents static copy.
        if self.id and self.course_instance.ending_time < timezone.now() and self.content:
            page = ExercisePage(self)
            page.is_loaded = True
            page.content_head = self.content_head
            page.content = self.content

        else:
            page = load_exercise_page(request, self.get_load_url(
                request, students, url_name), self)
            if self.id and (not self.content_time or \
                    self.content_time + datetime.timedelta(days=3) < timezone.now()):
                self.content_time = timezone.now()
                self.content_head = page.head
                self.content = page.content
                self.save()
        return page


class LearningObjectDisplay(models.Model):
    """
    Records views of learning objects.
    """
    learning_object = models.ForeignKey(LearningObject)
    profile = models.ForeignKey(UserProfile)
    timestamp = models.DateTimeField(auto_now_add=True)


class CourseChapter(LearningObject):
    """
    Chapters can offer and organize learning material as one page chapters.
    """
    generate_table_of_contents = models.BooleanField(default=False)

    def _is_empty(self):
        return not self.generate_table_of_contents


class BaseExercise(LearningObject):
    """
    The common parts for all exercises.
    """
    allow_assistant_viewing = models.BooleanField(default=True)
    allow_assistant_grading = models.BooleanField(default=False)
    min_group_size = models.PositiveIntegerField(default=1)
    max_group_size = models.PositiveIntegerField(default=1)
    max_submissions = models.PositiveIntegerField(default=10)
    max_points = models.PositiveIntegerField(default=100)
    points_to_pass = models.PositiveIntegerField(default=40)

    class Meta:
        app_label = 'exercise'

    def clean(self):
        """
        Validates the model before saving (standard method used in Django admin).
        """
        super().clean()
        if self.points_to_pass > self.max_points:
            raise ValidationError({
                'points_to_pass':_("Points to pass cannot be greater than max_points.")
            })
        if self.min_group_size > self.max_group_size:
            raise ValidationError({
                'min_group_size':_("Minimum group size cannot exceed maximum size.")
            })

    @property
    def is_submittable(self):
        return True

    def one_has_access(self, students, when=None):
        """
        Checks if any of the users can submit taking the granted extra time
        in consideration.
        """
        when = when or timezone.now()
        module = self.course_module
        if module.is_open(when=when) \
        or module.is_late_submission_open(when=when):
            return True
        if self.course_module.is_after_open(when=when):
            deviation = self.one_has_deadline_deviation(students)
            if deviation and when <= deviation.get_new_deadline():
                return True
        return False

    def one_has_deadline_deviation(self, students):
        deviation = None
        for profile in students:
            for d in self.deadlineruledeviation_set.filter(submitter=profile):
                if not deviation\
                        or d.get_new_deadline() > deviation.get_new_deadline():
                    deviation = d
        return deviation

    def get_submissions_for_student(self, user_profile, exclude_errors=False):
        if exclude_errors:
            submissions = user_profile.submissions.exclude_errors()
        else:
            submissions = user_profile.submissions
        return submissions.filter(exercise=self)

    def max_submissions_for_student(self, user_profile):
        """
        Calculates student specific max_submissions considering the possible
        MaxSubmissionsRuleDeviation for this student.
        """
        deviation = self.maxsubmissionsruledeviation_set \
            .filter(submitter=user_profile).first()
        if deviation:
            return self.max_submissions + deviation.extra_submissions
        return self.max_submissions

    def one_has_submissions(self, students):
        if self.max_submissions == 0:
            return True
        for profile in students:
            if self.get_submissions_for_student(profile, True).count() \
                < self.max_submissions_for_student(profile):
                return True
        return False

    def is_submission_allowed(self, profile):
        """
        Checks whether the submission to this exercise is allowed for the given
        user and generates a list of warnings.

        @return: (success_flag, warning_message_list)
        """
        success, warnings, students = self._check_submission_allowed(profile)
        return success, list(str(w) for w in warnings), students

    def _check_submission_allowed(self, profile):
        warnings = []
        students = [profile]

        if self.course_instance.ending_time < timezone.now():
            warnings.append(_('The course is archived. Exercises are offline.'))
            return False, warnings, students

        # Check enrollment requirements.
        enrollment = self.course_instance.get_enrollment_for(profile.user)
        if self.status == LearningObject.STATUS_ENROLLMENT:
            if not self.course_instance.is_enrollable(profile):
                warnings.append(_('You cannot enroll in the course.'))
                return False, warnings, students
        elif not enrollment and not self.course_instance.is_course_staff(profile.user):
            warnings.append(_('You must enroll at course home to submit exercises.'))
            return False, warnings, students

        # Check groups cannot be changed after submitting.
        submissions = list(self.get_submissions_for_student(profile))
        if len(submissions) > 0:
            if self._detect_group_changes(profile, enrollment, submissions[0]):
                warnings.append(_('You have previously submitted to this exercise with a different group. Group can only change between different exercises.'))
                return False, warnings, students
        elif self._detect_submissions(profile, enrollment):
            warnings.append(_('Some members of the group have already submitted to this exercise in a different group.'))
            return False, warnings, students

        # Get submitters.
        if enrollment and enrollment.selected_group:
            students = list(enrollment.selected_group.members.all())

        if not self.one_has_access(students):
            warnings.append(_('This exercise is not open for submissions.'))

        if not self.one_has_submissions(students):
            warnings.append(_('You have used the allowed amount of submissions for this exercise.'))

        # Check group size.
        if not (self.min_group_size <= len(students) <= self.max_group_size):
            if self.max_group_size == self.min_group_size:
                size = "{:d}".format(self.min_group_size)
            else:
                size = "{:d}-{:d}".format(self.min_group_size, self.max_group_size)
            warnings.append(
                _("This exercise can be submitted in groups of {size} students. "
                  "The size of your current group is {current}.")\
                .format(size=size, current=len(students))
            )

        success = len(warnings) == 0 \
            or all(self.course_instance.is_course_staff(p.user) for p in students)

        # If late submission is open, notify the student about point reduction.
        if self.course_module.is_late_submission_open():
            warnings.append(
                _('Deadline for the exercise has passed. Late submissions are allowed until'
                  '{date} but points are only worth {percent:d}%.').format(
                    date=date_format(self.course_module.late_submission_deadline),
                    percent=self.course_module.get_late_submission_point_worth(),
                ))

        return success, warnings, students

    def _detect_group_changes(self, profile, enrollment, submission):
        submitters = list(submission.submitters.all())
        if enrollment and enrollment.selected_group:
            return not enrollment.selected_group.equals(submitters)
        else:
            return len(submitters) > 1 or submitters[0] != profile

    def _detect_submissions(self, profile, enrollment):
        if enrollment and enrollment.selected_group:
            return not all(
                len(self.get_submissions_for_student(p)) == 0
                for p in enrollment.selected_group.members.all() if p != profile
            )
        return False

    def get_total_submitter_count(self):
        return UserProfile.objects \
            .filter(submissions__exercise=self) \
            .distinct().count()

    def get_async_hash(self, students):
        student_str = "-".join(
            sorted(str(userprofile.id) for userprofile in students)
        ) if students else "-"
        identifier = "{}.{:d}".format(student_str, self.id)
        hash_key = hmac.new(
            settings.SECRET_KEY.encode('utf-8'),
            msg=identifier.encode('utf-8'),
            digestmod=hashlib.sha256
        )
        return student_str, hash_key.hexdigest()

    def get_load_url(self, request, students, url_name="exercise"):
        if self.id:
            profile = None
            submission_count = 0
            if request.user.is_authenticated():
                profile = request.user.userprofile
                submission_count = self.get_submissions_for_student(request.user.userprofile).count()
            # Make async-new URL for the currently authenticated user.
            # The async handler will handle group selection at that time.
            profile_str, hash_key = self.get_async_hash([profile] if profile else [])
            student_str, _ = self.get_async_hash(students)
            return self._build_service_url(request, student_str, submission_count + 1, url_name, reverse(
                "async-new", kwargs={
                    "exercise_id": self.id if self.id else 0,
                    "student_ids": profile_str,
                    "hash_key": hash_key
                }
            ))
        else:
            return self.service_url

    def grade(self, request, submission,
            no_penalties=False, url_name="exercise"):
        """
        Loads the exercise feedback page.
        """
        student_str, _ = self.get_async_hash(submission.submitters.all())
        url = self._build_service_url(request, student_str, submission.ordinal_number(), url_name, reverse(
            "async-grade", kwargs={
                "submission_id": submission.id,
                "hash_key": submission.hash
            }))
        return load_feedback_page(request, url, self, submission,
            no_penalties=no_penalties)

    def modify_post_parameters(self, data, files, user, host, url):
        """
        Allows to modify submission POST parameters before they are sent to
        the grader. Extending classes may implement this function.
        """
        pass

    def _build_service_url(self, request, uid, ordinal_number, url_name, submission_url):
        """
        Generates complete URL with added parameters to the exercise service.
        """
        params = {
            "max_points": self.max_points,
            "submission_url": request.build_absolute_uri(submission_url),
            "post_url": request.build_absolute_uri(
                str(self.get_url(url_name))),
            "uid": uid or 0,
            "ordinal_number": ordinal_number,
        }
        return update_url_params(self.service_url, params)


class LTIExercise(BaseExercise):
    """
    Exercise launched by LTI or optionally ameding A+ protocol with LTI data.
    """
    lti_service = models.ForeignKey(LTIService)
    context_id = models.CharField(max_length=128, blank=True,
        help_text=_('Default: [hostname]/[course:url]/[instance:url]/'))
    resource_link_id = models.CharField(max_length=128, blank=True,
        help_text=_('Default: [aplusexercise:id]'))
    resource_link_title = models.CharField(max_length=128, blank=True,
        help_text=_('Default: Launch exercise'))
    aplus_get_and_post = models.BooleanField(default=False,
        help_text=_('Perform GET and POST from A+ to custom service URL with LTI data appended.'))

    def clean(self):
        """
        Validates the model before saving (standard method used in Django admin).
        """
        super().clean()
        if self.service_url and not has_same_domain(self.service_url, self.lti_service.url):
            raise ValidationError({
                'service_url':_("Exercise must be located in the LTI domain.")
            })

    def load(self, request, students, url_name="exercise"):
        if self.aplus_get_and_post:
            return super().load(request, students, url_name=url_name)

        url = self.service_url or self.lti_service.url
        lti = self._get_lti(students[0].user, request.get_host())

        # Render launch button.
        page = ExercisePage(self)
        page.content = self.content
        template = loader.get_template('exercise/model/_lti_button.html')
        page.content += template.render(Context({
            'service': self.lti_service,
            'url': url,
            'parameters': lti.sign_post_parameters(url),
            'title': self.resource_link_title,
        }))
        return page

    def _get_lti(self, user, host, add={}):
        return LTIRequest(
            self.lti_service,
            user,
            self.course_instance,
            host,
            self.resource_link_title or self.name,
            self.context_id or None,
            self.resource_link_id or "aplusexercise{:d}".format(self.id or 0),
            add=add,
        )

    def get_load_url(self, request, students, url_name="exercise"):
        url = super().get_load_url(request, students, url_name=url_name)
        if self.lti_service and students:
            lti = self._get_lti(students[0].user, request.get_host())
            return lti.sign_get_query(url)
        return url

    def modify_post_parameters(self, data, files, user, host, url):
        literals = {key: str(val[0]) for key,val in data.items()}
        lti = self._get_lti(user, host, add=literals)
        data.update(lti.sign_post_parameters(url))


class StaticExercise(BaseExercise):
    """
    Static exercises are used for storing submissions on the server, but not automatically
    assessing them. Static exercises may be retrieved by other services through the API.

    Chapters should be used for non submittable content.

    Should be deprecated as a contradiction to A+ ideology.
    """
    exercise_page_content = models.TextField()
    submission_page_content = models.TextField()

    def load(self, request, students, url_name="exercise"):
        page = ExercisePage(self)
        page.content = self.exercise_page_content
        return page

    def grade(self, request, submission,
            no_penalties=False, url_name="exercise"):
        page = ExercisePage(self)
        page.content = self.submission_page_content
        page.is_accepted = True
        return page

    def _is_empty(self):
        return not bool(self.exercise_page_content)


def build_upload_dir(instance, filename):
    """
    Returns the path to a directory where the attachment file should be saved.
    This is called every time a new ExerciseWithAttachment model is created.

    @param instance: the ExerciseWithAttachment object
    @param filename: the actual name of the submitted file
    @return: a path where the file should be stored, relative to MEDIA_ROOT directory
    """
    return "course_instance_{:d}/exercise_attachment_{:d}/{}".format(
        instance.course_instance.id,
        instance.id,
        safe_file_name(filename)
    )


class ExerciseWithAttachment(BaseExercise):
    """
    ExerciseWithAttachment is an exercise type where the exercise instructions
    are stored locally and the exercise will be graded by sending an additional
    attachment to the grader together with other POST data. The exercise page
    will contain a submission form for the files the user should submit if the
    files to be submitted are defined. Otherwise the instructions must contain
    the submission form.

    Could be deprecated as a contradiction to A+ purist ideology.
    """
    files_to_submit = models.CharField(max_length=200, blank=True,
        help_text=_("File names that user should submit, use pipe character to separate files"))
    attachment = models.FileField(upload_to=build_upload_dir)

    class Meta:
        verbose_name_plural = "exercises with attachment"

    def get_files_to_submit(self):
        """
        Returns a list of the file names that user should submit with this exercise.
        """
        if len(self.files_to_submit.strip()) == 0:
            return []
        else:
            files = self.files_to_submit.split("|")
            return [filename.strip() for filename in files]

    def load(self, request, students, url_name="exercise"):
        page = ExercisePage(self)
        page.content = self.content

        # Adds the submission form to the content if there are files to be
        # submitted. A template is used to avoid hard-coded HTML here.
        if self.get_files_to_submit():
            template = loader.get_template('exercise/model/_file_submit_form.html')
            context = Context({'files' : self.get_files_to_submit()})
            page.content += template.render(context)

        return page

    def modify_post_parameters(self, data, files, user, host, url):
        """
        Adds the attachment file to post parameters.
        """
        import os
        files['content_0'] = (
            os.path.basename(self.attachment.path),
            open(self.attachment.path, "rb")
        )


def _delete_file(sender, instance, **kwargs):
    """
    Deletes exercise attachment file after the exercise in database is removed.
    """
    default_storage.delete(instance.attachment.path)
post_delete.connect(_delete_file, ExerciseWithAttachment)
