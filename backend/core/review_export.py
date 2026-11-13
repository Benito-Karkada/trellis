"""Staff-only worksheet data. No outbound transfer occurs at these endpoints."""
import csv
import io
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from .course_settings import staff_course
from .studio import require_authoring_access
from .models import Membership
from .submission_review import report_data, WEIGHTS

COLUMNS=['Enrollment ID','GTID','Name','Sus index / 100','Timing metric','Code metric','First-pass metric','Focus metric',
    'Timing contribution','Code contribution','First-pass contribution','Focus contribution','Largest contributors','Review reasons',
    'Data coverage','Positive submission gaps','Runs','Submits','Analyzed exercises','Flagged exercises','First-pass eligible exercises',
    'First passes without Run','Focus episodes','Tab-hidden episodes','Window-only episodes','Code revisions',
    'Revisions after unsuccessful attempts','Unassessed attempts','As of UTC','Gap baseline seconds','Focus reference','Identifier status']
KEYS=('timing','code','first_pass','focus')
def worksheet_formulas(number):
    result={'D':f'=IF(COUNT(E{number}:H{number})=0,"",ROUND(SUMPRODUCT(E{number}:H{number},$AJ$2:$AM$2),1))'}
    for source,target,weight in zip('EFGH','IJKL',('AJ','AK','AL','AM')):
        result[target]=f'=IF(ISNUMBER({source}{number}),{source}{number}*${weight}$2,"")'
    return result


def cell_text(value):
    if not isinstance(value,str):return value
    return "'"+value if value.lstrip().startswith(('=','+','-','@')) or value.startswith(('\t','\r','\n')) else value


def export_data(request,course):
    # Deny student-view sessions and require an active staff role in this course,
    # even when called internally. REST separately checks three required scopes.
    require_authoring_access(request,course)
    original=request.GET;params=original.copy();params['page']='0';request.GET=params
    try:
        data=report_data(request,course);students=list(data['results'])
        for page in range(1,(data['total']+49)//50):
            params['page']=str(page);request.GET=params
            students.extend(report_data(request,course)['results'])
    finally:request.GET=original
    ids=dict(Membership.objects.filter(course=course,active=True,role='student').values_list('pk','external_ids'))
    at=timezone.now().isoformat();rows=[];formulas=[]
    for number,student in enumerate(students,2):
        gtid=str((ids.get(student['membership_id']) or {}).get('gtid',''))
        components=student['components'];values=[components[k]['raw_value'] for k in KEYS]
        contrib=[components[k]['contribution'] for k in KEYS]
        ranked=sorted(((k,components[k]['contribution']) for k in KEYS if components[k]['contribution'] is not None and components[k]['contribution']>0),key=lambda p:-p[1])
        dominant='; '.join(f'{k.replace("_"," ")}: {v:g} points' for k,v in ranked)
        missing=[k.replace('_',' ') for k in KEYS if components[k]['value'] is None]
        coverage=f'{4-len(missing)}/4 metrics observed'+('; unavailable: '+', '.join(missing) if missing else '')
        row=[str(student['membership_id']),gtid,student['name'],student['index'],*values,*contrib,dominant,
            '; '.join(student['reasons']),coverage,*[student[k] for k in ('gap_count','runs','submits','analyzed_parts','flagged_parts',
            'first_pass_eligible','first_pass_without_run','focus_changes','tab_hidden','window_only','code_revisions',
            'revisions_after_unsuccessful_attempts','unassessed_attempts')],at,data['policy']['tau_seconds'],data['policy']['focus_reference'],
            'GTID available' if gtid else 'Missing GTID']
        rows.append([cell_text(v) for v in row])
        formulas.append(worksheet_formulas(number))
    return {'schema_version':2,'course_id':course.pk,'course_title':course.title,'as_of':at,'columns':COLUMNS,'rows':rows,
        'formulas':formulas,'total':len(rows),'weights':WEIGHTS,'policy':data['policy'],
        'methodology':'Private review aid, not a probability of AI use or proof of misconduct. No grades change. Unknown metrics are not renormalized. Focus records do not identify destinations.'}


def response(request,course):
    data=export_data(request,course)
    if request.GET.get('format')=='csv':
        stream=io.StringIO();writer=csv.writer(stream);writer.writerow(data['columns']);writer.writerows(data['rows'])
        result=HttpResponse('\ufeff'+stream.getvalue(),content_type='text/csv; charset=utf-8')
        result['Content-Disposition']='attachment; filename="trellis-submission-review.csv"'
    else:result=JsonResponse(data)
    result['Cache-Control']='private, no-store';return result


def download(request):return response(request,staff_course(request))
