from dvadmin.system.models import Users, JiraProject, JiraIssue, IssueComment
from dvadmin.system.views.user import UserSerializer

from dvadmin.utils.serializers import CustomModelSerializer

from dvadmin.utils.viewset import CustomModelViewSet
from dvadmin.utils.json_response import DetailResponse, SuccessResponse, ErrorResponse
from rest_framework.decorators import action
from dingtalkchatbot.chatbot import DingtalkChatbot
from enum import Enum
from datetime import datetime, timedelta
from django.db.models import Count, DateField, Case, When, F
from django.db.models.functions import Coalesce


class JiraProjectSerializer(CustomModelSerializer):
    class Meta:
        model = JiraProject
        fields = '__all__'


class IssueCommentSerializer(CustomModelSerializer):
    author = UserSerializer()

    class Meta:
        model = IssueComment
        fields = '__all__'


class JiraIssueSerializer(CustomModelSerializer):
    comments = IssueCommentSerializer(many=True, read_only=True)

    class Meta:
        model = JiraIssue
        fields = '__all__'


class JiraViewSet(CustomModelViewSet):
    queryset = JiraProject.objects.all()
    serializer_class = JiraProjectSerializer

    @action(methods=['GET'], detail=False)
    # 获取项目列表
    def get_project_list_page(self, request):
        queryset = JiraProject.objects.all()
        serializer = JiraProjectSerializer(queryset, many=True)
        data = serializer.data
        return SuccessResponse(data=data, total=len(data), msg="获取成功")

    @action(methods=['POST'], detail=False)
    # 编辑项目信息
    def update_project(self, request):
        data = request.data
        data1 = {
            'name': data.get('name'),
            'key': data.get('key'),
            'description': data.get('description'),
            'manager_id': data.get('manager'),
            'ding_webhook': data.get('ding_webhook')
        }
        JiraProject.objects.filter(id=data.get('id')).update(**data1)
        return DetailResponse(msg='更新成功')

    @action(methods=['POST'], detail=False)
    # 删除项目
    def delete_project(self, request):
        data = request.data
        JiraProject.objects.filter(id=data.get('id')).delete()
        return DetailResponse(msg='更新成功')

    @action(methods=['GET'], detail=False)
    # 获取所有项目列表
    def get_project_list(self, request):
        queryset = JiraProject.objects.all()
        serializer = JiraProjectSerializer(queryset, many=True)
        data = serializer.data
        return DetailResponse(data=data)

    @action(methods=['GET'], detail=False)
    def get_all_issue(self, request):
        project_id = request.query_params.get('project_id')
        if not project_id:
            return ErrorResponse(msg='项目不存在')
        status = request.query_params.get('status')
        queryset = JiraProject.objects.filter(project_id=project_id)
        if status is not None:
            queryset = queryset.filter(status=status)
        issues = queryset.all()
        queryset = JiraProject.objects.all()
        serializer = JiraProjectSerializer(queryset, many=True)
        data = serializer.data
        return DetailResponse(data=data)

    @action(methods=['POST'], detail=False)
    # 获取单个issue在jiraissue表中的所有字段加上issuecomment表中相对应issue_id的comment
    def get_issue_detail(self, request):
        data = request.data
        issue_id = data.get('id')
        issue = JiraIssue.objects.get(id=issue_id)
        serializer = JiraIssueSerializer(issue)
        comment = IssueComment.objects.filter(issue_id=issue_id)
        comment_serializer = IssueCommentSerializer(comment, many=True)
        serialized_data = serializer.data
        serialized_data['comments'] = comment_serializer.data
        return DetailResponse(data=serialized_data)

    @action(methods=['GET'], detail=False)
    # 获取请求中projectid和status的相应issue的所有字段
    def get_issue_list(self, request):
        queryset = JiraIssue.objects.filter(project_id=request.query_params.get('project_id'))
        status = request.query_params.get('status')
        if status:
            queryset = queryset.filter(status=status)
        serializer = JiraIssueSerializer(queryset, many=True)
        serialized_data = serializer.data
        return DetailResponse(data=serialized_data)

    @action(methods=['GET'], detail=False)
    # 获取所有用户的id和name
    def get_jira_user(self, request):
        queryset = Users.objects.all()
        serializer = UserSerializer(queryset, many=True)
        serialized_data = serializer.data
        processed_data = [{'id': user['id'], 'name': user['name']} for user in serialized_data]
        return DetailResponse(data=processed_data)

    @action(methods=['POST'], detail=False)
    def add_issue(self, request):
        data = request.data
        project_id = data.get('project_id')
        project = JiraProject.objects.get(id=project_id)
        count = JiraIssue.objects.filter(project_id=project_id).count()
        count = count + 1
        data['signal_number'] = str(project.key) + '-' + str(count)
        data['creator_id'] = request.user.id
        data['modifier'] = request.user.id
        data['status'] = 1
        JiraIssue.objects.create(**data)
        assigned_user = Users.objects.get(id=data['assigned_id'])
        user_serializer = UserSerializer(assigned_user)
        assigned_name = user_serializer.data.get('name')
        data['assigned_name'] = assigned_name
        project_id2 = JiraProject.objects.get(id=data['project_id'])
        Project_Serializer = JiraProjectSerializer(project_id2)
        project_name = Project_Serializer.data.get('name')
        # 获取用户手机号码
        assigned_mobile = user_serializer.data.get('mobile')

        # 在发送钉钉消息时添加 mobiles 参数
        send_dingtalk_message(project.ding_webhook,
                              '有新的issue：' + '来自于项目' + project_name + '， issue标题为:' + data['name'] + ' ，指派给' + assigned_name,
                              mobiles=[assigned_mobile])
        return DetailResponse(data='创建成功')

    @action(methods=['POST'], detail=False)
    def update_issue(self, request):
        data = request.data
        issue = JiraIssue.objects.filter(id=data.get('id'))
        if not issue:
            return ErrorResponse(msg='issue不存在')
        data.pop('id', None)
        data['modifier'] = request.user.id
        data['update_datetime'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        issue.update(**data)
        return DetailResponse(data='保存成功')

    @action(methods=['POST'], detail=False)
    def resolve_issue(self, request):
        data = request.data
        issue_id = data.get('id')
        issue = JiraIssue.objects.filter(id=issue_id)
        if not issue:
            return ErrorResponse(msg='issue不存在')
        update_data = {'resolve_datetime': data.get('resolve_datetime'), 'modifier': request.user.id, 'status': 2,
                       'update_datetime': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'actual_hours': data.get('actual_hours')}
        JiraIssue.objects.filter(id=issue_id).update(**update_data)
        if data.get('comment'):
            obj = {
                'body': data.get('comment'),
                'author_id': request.user.id,
                'issue_id': issue_id
            }
            IssueComment.objects.create(**obj)
        issue = JiraIssue.objects.get(id=issue_id)
        issue_serializer = JiraIssueSerializer(issue)
        project = JiraProject.objects.get(id=issue_serializer.data.get('project'))
        project_serialize = JiraProjectSerializer(project)
        if project_serialize.data.get('ding_webhook'):
            user = Users.objects.get(id=request.user.id)
            user_serializer = UserSerializer(user)
            send_dingtalk_message(project.ding_webhook, user_serializer.data.get('name')+'解决了issue:' + issue_serializer.data.get('signal_number')+' '+issue_serializer.data.get('name'), mobiles=None)
        return DetailResponse(data='保存成功')

    @action(methods=['POST'], detail=False)
    def confirm_issue(self, request):
        data = request.data
        issue = JiraIssue.objects.filter(id=data.get('id'))
        if not issue:
            return ErrorResponse(msg='issue不存在')
        params = {
            'pending_datetime': data.get('pending'),
            'expected_hours': data.get('expected_hours'),
            'update_datetime': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'modifier': request.user.id
        }
        JiraIssue.objects.filter(id=data.get('id')).update(**params)
        return DetailResponse(msg='保存成功')

    @action(methods=['GET'], detail=False)
    def issue_analysis(self, request):
        issue_count = JiraIssue.objects.count()
        unpending_count = JiraIssue.objects.filter(status=1, pending_datetime__isnull=True).count()
        pending_count = JiraIssue.objects.filter(status=1, pending_datetime__isnull=False).count()
        resolve_count = JiraIssue.objects.filter(status=2).count()
        seven_days_ago = datetime.now() - timedelta(days=7)
        daily_counts = JiraIssue.objects.filter(
            create_datetime__gte=seven_days_ago
        ).values('create_datetime__date').annotate(
            created_count=Coalesce(Count('id'), 0),
            resolved_count=Coalesce(Count(Case(When(resolve_datetime__date=F('create_datetime__date'), then=1))), 0)
        ).order_by('create_datetime__date')
        daily_data = []
        current_date = seven_days_ago.date()
        for entry in daily_counts:
            while entry['create_datetime__date'] > current_date:
                daily_data.append({'date': current_date, 'created_count': 0, 'resolved_count': 0})
                current_date += timedelta(days=1)
            daily_data.append({
                'date': entry['create_datetime__date'],
                'created_count': entry['created_count'],
                'resolved_count': entry['resolved_count'],
            })
            current_date += timedelta(days=1)

        while current_date <= datetime.now().date():
            daily_data.append({'date': current_date, 'created_count': 0, 'resolved_count': 0})
            current_date += timedelta(days=1)

        projects = (JiraIssue.objects.filter(resolve_datetime__isnull=True).values('project__name')
                    .annotate(unresolve_count=Count('id')).order_by('project__name'))
        print(projects)
        project_data = []
        for entry in projects:
            project_data.append({
                'project_name': entry['project__name'],
                'unresolve_count': entry['unresolve_count']
            })
        data = {
            'issue_count': issue_count,
            'unpending_count': unpending_count,
            'pending_count': pending_count,
            'resolve_count': resolve_count,
            'daily_count': daily_data,
            'unresolved_project_count': project_data
        }
        return DetailResponse(data=data)


def send_dingtalk_message(webhook, msg, mobiles):
    try:
        bot = DingtalkChatbot(webhook)
        if mobiles:
            bot.send_text(msg=msg, at_mobiles=mobiles)
        else:
            bot.send_text(msg=msg)
        print(webhook)
        print(msg)
        print(mobiles)
        print("Dingtalk message sent successfully!")
    except Exception as e:
        print(f"Error sending Dingtalk message: {str(e)}")
