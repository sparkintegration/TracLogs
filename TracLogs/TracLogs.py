import re
import datetime
import calendar
import time
import copy

from trac.core import *
from trac.util import Markup
from trac.web import IRequestHandler
from trac.timeline import ITimelineEventProvider
from trac.web.chrome import INavigationContributor, ITemplateProvider, add_stylesheet, add_script
from trac.perm import IPermissionRequestor, PermissionCache, DefaultPermissionStore
from trac.env import IEnvironmentSetupParticipant, Environment
from trac.wiki import wiki_to_html
from trac.mimeview.api import Context
from trac.db import Table, Column, Index, DatabaseManager
from trac.env import Environment
from tracsqlhelper import *

from genshi.builder import tag

class TracLogs(Component):
    implements(IRequestHandler, ITemplateProvider, INavigationContributor, ITimelineEventProvider, IPermissionRequestor, IEnvironmentSetupParticipant)
    
    def environment_created(self):
        """Called when a new Trac environment is created."""
        if self.environment_needs_upgrade(None):
            self.upgrade_environment(None)

    def environment_needs_upgrade(self, db):
        """Called when Trac checks whether the environment needs to be upgraded.
        
        Should return `True` if this participant needs an upgrade to be
        performed, `False` otherwise.
        """
        version = self.version()
        self.log.debug("Version is %s" % version)
        return version < len(self.upgrade_steps)

    def upgrade_environment(self, db):
        """Actually perform an environment upgrade.
        
        Implementations of this method should not commit any database
        transactions. This is done implicitly after all participants have
        performed the upgrades they need without an error being raised.
        """
        if not self.environment_needs_upgrade(db):
            return

        version = self.version()
        for version in range(self.version(), len(self.upgrade_steps)):
            for step in self.upgrade_steps[version]:
                step(self)
        qry = "update system set value='%s' where name='TracLogs.db_version';" % len(self.upgrade_steps)
        db = self.env.get_db_cnx()
        cursor = db.cursor()
        cursor.execute(qry)
        
    def version(self):
        """returns version of the database (an int)"""
        qry = "select value from system where name = 'TracLogs.db_version';"
        db = self.env.get_db_cnx()
        cursor = db.cursor()
        cursor.execute(qry)
        rows = cursor.fetchall()
        if rows:
            return int(rows[0][0])
        return 0
        
    def create_db(self):

        logs_table = Table('logs', key=('log_id'))[
            Column('log_id', auto_increment=True),
            Column('user_id', type='text'),
            Column('log_date', type='date'),
            Column('start', type='time'),
            Column('end', type='time'),
            Column('extra', type='double'),
            Column('updated', type='timestamp'),
            Index(['log_id']),
            Index(['user_id'])
        ]
            
        log_entries_table = Table('log_entries', key=('log_entry_id'))[
            Column('log_entry_id', auto_increment=True),
            Column('log_id', type='int'),
            Column('project_id', type='int'),
            Column('hours', type='double'),
            Column('notes', type='text'),
            Column('updated', type='timestamp'),
            Index(['log_id']),
            Index(['log_entry_id'])
        ]
        
        # CREATE TABLE c_projects (id integer primary key autoincrement, parentId integer,
        #             customerId integer,
        #             name text,
        #             data text,
        #             budget integer default 0,
        #             active boolean default 1,
        #             workon boolean default 1);
        
        projects_table = Table('c_projects', key=('id'))[
            Column('id', auto_increment=True),
            Column('parentId', type='int'),
            Column('customerId', type='int'),
            Column('name', type='text'),
            Column('data', type='text'),
            Column('budget', type='int'),
            Column('active', type='boolean'),
            Column('workon', type='boolean')
        ]

        #CREATE TABLE customers ( id integer primary key autoincrement, name text, data text);
        customers_table = Table('customers', key=('id'))[
            Column('id', auto_increment=True),
            Column('name', type='text'),
            Column('data', type='text')
        ]

        create_table(self.env, logs_table)
        create_table(self.env, log_entries_table)
        create_table(self.env, projects_table)
        create_table(self.env, customers_table)
        qry = "insert into system (name, value) values ('TracLogs.db_version', '1');"
        db = self.env.get_db_cnx()
        cursor = db.cursor()
        cursor.execute(qry)
        
    upgrade_steps = [[create_db]]    
    
    #IPermissionRequestor methods
    def get_permission_actions(self):
        """
        Returns the permissions used by this plugin.
        LOGS_EDIT allows a user to modify log entries (anyones, not just their own, right now)
        LOGS_VIEW allows a user to view log entries (including in the timeline)
        LOGS_REPORT allows a user to generate reports based on the log data
        """
        return ['LOGS_EDIT', 'LOGS_REPORT', 'LOGS_VIEW']
    
    #ITimelineEventProvider methods
    def get_timeline_filters(self, req):
        if req.perm.has_permission('LOGS_VIEW'):
            yield ('dailylogs', 'Daily Logs')

    def get_timeline_events(self, req, start, stop, filters):
        """Returns log entries whose updated flag falls within the filter values."""
        if req.perm.has_permission('LOGS_VIEW'):
            if 'dailylogs' in filters:
                db = self.env.get_db_cnx()
                cursor = db.cursor()
                # self.log.debug("Start: %s", start)
                # self.log.debug("End:  %s", stop)
                qry = "SELECT log_id, user_id, log_date, start, end, extra, updated FROM logs WHERE updated >= %s AND updated <= %s ORDER BY updated, log_date" 
                t_log_id, t_user_id, t_log_date, t_start, t_end, t_extra, t_updated = 0,1,2,3,4,5,6
                vars = ("%s" % start, "%s" % stop)
                cursor.execute(qry,vars)
                rows = cursor.fetchall()
                updates = {}
                for row in rows:
                    timestamp = time.mktime(row[t_updated].timetuple())
                    subject = "Logs for %s edited" % (row[t_log_date])
                    updates['%s' % row[t_log_id]] = row[t_updated]
                    yield "dailylogs", timestamp, str(row[t_user_id]), {"user_id":row[t_user_id], "date":row[t_log_date], "summary": str(subject), "description":""}
                qry = "SELECT le.log_entry_id, le.log_id, le.project_id, le.hours, le.notes, le.updated, l.log_date, l.user_id "
                qry += " FROM log_entries as le LEFT JOIN logs as l ON (le.log_id = l.log_id) WHERE le.updated >= %s AND le.updated <= %s"
                qry += " ORDER BY le.updated;"
                vars =  ('%s' % start, '%s' % stop)
                l_log_entry_id, l_log_id, l_project_id, l_hours, l_notes, l_updated, l_log_date, l_user_id = 0,1,2,3,4,5,6,7
                cursor.execute(qry,vars)
                rows = cursor.fetchall()
                for row in rows:
                    if str(row[l_log_id]) not in updates.keys() or updates['%s' % row[l_log_id]] != row[l_updated]:
                        timestamp = time.mktime(row[l_updated].timetuple()) 
                        # self.log.debug("TimeStamp: %s", timestamp)
                        # self.log.debug("Time: %s", row[l_updated])
                        subject = "Logs for %s edited" % (row[l_log_date])
                        updates['%s'% row[l_log_id]] = row[l_updated]
                        yield "dailylogs", timestamp, str(row[l_user_id]), {"user_id":row[l_user_id], "date":row[l_log_date], "summary": str(subject), "description":""}
        
    def render_timeline_event(self, context, field, event):
        (classname, timestamp, user, data) = event
        if field == 'url':
            week = data['date'].strftime("%W")
            year = data['date'].strftime("%Y")
            return str(context.href('logs', 'edit', data['user_id'], year, week)) + "#%s" % str(data['date'])
        elif field == "title":
            return data["summary"]
        elif field == "description":
            return data["description"]
    
    # INavigationContributor methods
    def get_active_navigation_item(self, req):
        return 'Logs'
        
    def get_navigation_items(self, req):
        if not req.perm.has_permission('LOGS_VIEW'):
            return
        yield 'mainnav', 'Logs', \
               tag.a('Logs', href=req.href.logs())
    
    #IRequestProvider functions
    def match_request(self, req):
        """
        Matches requests to the /logs URL.  Only matches if the current user has LOGS_VIEW permission.
        Puts the rest of the request after /logs/ into a variable called 'rest' in the req.args dictionary
        """
        if not req.perm.has_permission('LOGS_VIEW'):
            return False
        match = re.match(r'/logs/(.*?)$', req.path_info)
        if match or req.path_info == '/logs':
            if match:
                req.args['rest'] = match.group(1)
            else:
                req.args['rest'] = ""
            return True
    
    def process_request(self, req):
        """
        Request dispatcher.  Looks at the request and calls the appropriate handler function or redirects
        to the appropriate URL.
        """
        #for key in req.args.keys():
            #if "RemoveEntry" in key or "AddEntry" in key:
                #day = key.split("_")[1]
                #self.log.info("Found day: %s" % str(day))
                #(action, user_id, year, curWeek) = req.args['rest'].split("/")
                #req.redirect('%s/edit/%s/%s/%s#%s' % (req.href.logs(), user_id, year, curWeek, str(day)))
        #if week is in req.args, then this must be a submitted form from the edit page,
        #so redirect back to the appropriate place
        if 'week' in req.args:
            curWeek = req.args['week']
            year = req.args['year']
            user_id = req.args['user_id']
            req.redirect('%s/edit/%s/%s/%s' % (req.href.logs(), user_id, year, curWeek))
        add_stylesheet(req, 'logs/css/default.css')
        self.handlers = {'':self.index, 'edit':self.edit, 'report':self.report,'report_C':self.report_C,'report_P':self.report_P, 'report_U':self.report_U,'report_B':self.report_B,}
        cmds = req.args['rest'].split('/')
        #call a handler based on  the first argument
        return self.handlers[cmds[0]](req)
    
    def index(self, req):
        """
        Handler for the index page.  Displays a list of users whose logs can be viewed/edited.
        """
        db = self.env.get_db_cnx()
        data = {}
        localCur = db.cursor()
        users = []
        users_report = []
        perms = DefaultPermissionStore(self.env)
        for user_data in self.env.get_known_users():
            user_perms = perms.get_user_permissions(user_data[0])
            # self.log.debug("Permission: %s %r"% (user_data[0],user_perms))
            if 'LOGS_EDIT' in user_perms:
                users.append({"user_id":user_data[0], "name":user_data[0]})
            else:
                users_report.append({"user_id":user_data[0], "name":user_data[0]})
        (weeks, curWeek) = self.getWeeks()
        year = datetime.date.today().year
        data['year'] = year
        data['curWeek'] = curWeek
        data['users'] = users
        data['user'] = req.authname 
        data['month'] = str(datetime.date.today().month)
        if req.perm.has_permission('LOGS_REPORT'):
            data['users_report'] = users_report
            data['reports_enabled'] = True
            data['projects'] = self.getProjects(localCur)
            data['years'] = range(2007, datetime.date.today().year + 2)
            data['months'] = ['0'+str(h) for h in range(1,10)]+[str(h) for h in range(10,13)]
            data['days'] = ['0'+str(h) for h in range(1,10)]+[str(h) for h in range(10,32)]
            data['day'] = datetime.date.today().day
            data['customers'] = self.getCustomers(localCur)
        data['base_url'] = req.href.logs()
        # data['base_url'] = self.env.href.logs()
        add_script(req, 'logs/js/logs.js')
        return 'logsindex.html', data, None
    #Page handlers

    def report(self, req):
        """
        Generates a report. Old Legacy Report
        """
        if req.perm.has_permission('LOGS_REPORT'):

            db = self.env.get_db_cnx()
            cursor = db.cursor()
            
            ctxx = Context(self.env, req)('wiki','WikiStart')
            
            if not isinstance(req.args['projects'], list):
                req.args['projects'] = [req.args['projects']]
            users = {}
            for user_data in self.env.get_known_users():
                users["%s"%user_data[0]] = user_data[0]

            #qry = "SELECT user_id, name FROM users WHERE enabled=1 ORDER BY name"
            #cursor.execute(qry)
            #for row in cursor.fetchall():
            #    users[str(row['user_id'])] = row['name']
            debug = ""
            start_month = req.args['month']
            end_month = start_month
            if start_month == "ALL":
                start_month = 1
                end_month = 12
            start_year = req.args['year']
            # self.log.debug("Projects: %r", req.args['projects'])
            projects = [str(t) for t in req.args['projects']]
            projectInfo = {}
            for t in req.args['projects']:
                projectInfo[str(t)] = self.getProjectById(cursor,t)
            
            data = {}
            data["userData"] = {}
            userData = data["userData"]
            weeks = []
            if not isinstance(req.args['users'], list): 
                user_req = [req.args['users']] 
            else: 
                user_req = req.args['users']
            for user_id in user_req:
                userData[user_id] = {}
                qry = "SELECT log_id, user_id, log_date, start, end, extra, updated FROM logs WHERE user_id='%s' AND log_date>='%s-%s-01' AND log_date<='%s-%s-31' ORDER BY log_date" \
                    % (user_id, start_year, start_month, start_year, end_month)
                cursor.execute(qry)
                rows = cursor.fetchall()
                l_log_id, l_user_id, l_log_date, l_start, l_end, l_extra, l_updated  = 0,1,2,3,4,5,6
                userData[user_id]['logs'] = {}
                userData[user_id]['projects'] = {}
                for row in rows:
                    qry = "SELECT log_entry_id, log_id, project_id, hours, notes, updated FROM log_entries WHERE log_id='%s'" % row[l_log_id]
                    cursor.execute(qry)
                    entries = cursor.fetchall()
                    e_log_entry_id, e_log_id, e_project_id, e_hours, e_notes, e_updated = 0,1,2,3,4,5
                    week = str(self.getWeekStart(row[l_log_date]))
                    if week not in weeks:
                        weeks.append(week)
                    for entry in entries:
                        #entry[e_project_id] = str(entry[e_project_id])
                        if '%s' % entry[e_project_id] in projects:
                            if '%s' % entry[e_project_id] not in userData[user_id]['projects']:
                                userData[user_id]['projects']['%s' % entry[e_project_id]] = {}
                            projectData = userData[user_id]['projects']['%s' % entry[e_project_id]]
                            if "total" not in projectData:
                                projectData["total"] = 0
                            if "weeks" not in projectData:
                                projectData["weeks"] = {}
                            if week not in projectData["weeks"]:
                                projectData["weeks"][week] = 0.0
                            projectData["weeks"][week] = projectData["weeks"][week] + float(entry[e_hours])
                            projectData["total"] = projectData["total"] + float(entry[e_hours])
                            if '%s' % entry[e_project_id] not in userData[user_id]['logs']:
                                userData[user_id]['logs']['%s' % entry[e_project_id]] = []
                            if entry[e_notes] != "":
                                lines = []
                                for line in entry[e_notes].split("\n"):
                                    line = line.strip(' \t*[];-!@#$%^&*()_+-=')
                                    line = " * " + line.capitalize()
                                    lines.append(line)
                                notes = "\n".join(lines)
                                userData[user_id]['logs']['%s' % entry[e_project_id]].append((row[l_log_date], entry[e_project_id], notes))
                #userData[user_id]['logs'].sort()

            weeks.sort()
            data['weeks'] = weeks
            data['users'] = users
            data['projects'] = projects
            data['projectInfo'] = projectInfo
            data['debug'] = debug
            data['data'] = data
            data["today"] = datetime.date.today()
            if req.args['month'] == 'ALL':
                data["report_date"] = "%s" % req.args['year']
            else:    
                data["report_date"] = "%s" % (datetime.date(int(req.args['year']), int(req.args['month']), 1).strftime("%B %Y"))
            data["user_filter"] = ", ".join([users[str(uid)] for uid in user_req])
            # self.log.info("Projects: %s User projects: %s" % (str(projects), str(req.args['projects'])))
            data["project_filter"] = ", ".join(projects)
        return 'report.html', data, None
   
    def report_C(self,req):
        """
        Handler for Customer Report requests
        Get list of projects for customer, get user work for projects during month/year
        """
        data = {}
        reportData = {}
        qry_dbg = ""
        db = self.env.get_db_cnx()
        cursor = db.cursor()
        
        customer = req.args['customer']
        month = req.args['month']
        year = req.args['year']
        base_url = req.href.logs()
        data['customer'] = self.getCustomerById(cursor,customer)

        parentProjects = self.getParentProjects(cursor,customer)  
        projects = parentProjects[:]
        for proj in parentProjects:
            subProjects = self.getReportSubProjects(proj['id'],proj['name'])
            projects.extend(subProjects)

        for project in projects:
            pId = '%s' % project['id']
            reportData[pId] = {'name':project['name'],'users':{}}
            reportData[pId]['log_hours'] = 0
            reportData[pId]['ticket_hours'] = 0
            reportData[pId]['total_hours'] = 0
            reportData[pId]['budget_hours'] = project['budget']
            reportData[pId]['remaining_hours'] = 0
            #get data from logs
            logEntries = self.getProjectLogs(cursor, project['id'],month, year, month, year)
            # entry = {'log_entry_id', 'log_id', 'project_id', 'user_id', 'log_date', 'hours', 'notes'}
            for entry in logEntries:
                uId = '%s' % entry['user_id']
                log_date = entry['log_date']
                if uId not in reportData[pId]['users']:
                    reportData[pId]['users'][uId] = {'user_log_hours':0,'user_ticket_hours':0,'user_total_hours':0,'dates':{},'tickets':{},}
                if entry['notes'] == '':
                    entry['notes'] = "* No Comments"
                if log_date not in reportData[pId]['users'][uId]['dates']:
                    week = str(log_date.isocalendar()[1])
                    if week == "53":
                        week = "0"
                    url = base_url + '/edit/' + uId + '/' + year + '/'+ week + '#' + str(log_date)
                    logData = []
                    reportData[pId]['users'][uId]['dates'][log_date] = [url,logData]
                reportData[pId]['users'][uId]['dates'][log_date][1].append([entry['notes'], entry['hours']])
                reportData[pId]['log_hours'] += float(entry['hours'])
                reportData[pId]['users'][uId]['user_log_hours'] += float(entry['hours']) 
                reportData[pId]['users'][uId]['user_total_hours'] += float(entry['hours']) 
            
            #get data from ticket_hours
            ticketEntries = self.getTicketLogs(cursor, project['id'], month, year, month, year)
            # {"user_id", "ticket_id", "start_time", "ticket_time", "time_comments","ticket_summary"}
            for entry in ticketEntries:
                uId = '%s' % entry['user_id']
                ticketId = '%s' % entry['ticket_id']
                if uId not in reportData[pId]['users']:
                    reportData[pId]['users'][uId] = {'user_log_hours':0,'user_ticket_hours':0,'user_total_hours':0,'dates':{},'tickets':{},}
                if ticketId not in reportData[pId]['users'][uId]['tickets']:
                    reportData[pId]['users'][uId]['tickets'][ticketId] = {'ticket_summary':entry['ticket_summary'],'ticket_time':0,'ticketData':[]}
                if entry['time_comments'] != '':
                    reportData[pId]['users'][uId]['tickets'][ticketId]['ticketData'].append(entry['time_comments'])
                reportData[pId]['users'][uId]['tickets'][ticketId]['ticket_time'] += float(entry['ticket_time'])
                reportData[pId]['users'][uId]['user_ticket_hours'] += float(entry['ticket_time'])
                reportData[pId]['users'][uId]['user_total_hours'] += float(entry['ticket_time']) 
                reportData[pId]['ticket_hours'] += float(entry['ticket_time'])

            reportData[pId]['total_hours'] = reportData[pId]['log_hours'] + reportData[pId]['ticket_hours']
            reportData[pId]['user_count'] = len(reportData[pId]['users']) + 1
            reportData[pId]['remaining_hours'] = reportData[pId]['budget_hours'] - reportData[pId]['total_hours']
            # remove empty projects
            if len(reportData[pId]['users']) == 0:
                del reportData[pId]
         
        data['reportData'] = reportData
        data['report_date'] = "%s, %s" % (month, year)
        data["today"] = datetime.date.today()
        data['proj_url'] = req.href.c_projects()
        data['ticket_url'] = req.href.ticket()
        # self.log.debug("reportData: %r", reportData)
        return 'report_C.html', data,None

    def report_P(self,req):
        
        data = {}
        reportData = {}
        db = self.env.get_db_cnx()
        cursor = db.cursor()

        project_id = req.args['project']

        start_month = req.args['start_month']
        start_year = req.args['start_year']
        end_month = req.args['end_month']
        end_year = req.args['end_year']
        
        base_url = req.href.logs()

        mainProject = self.getProjectById(cursor,project_id)
        subProjects = self.getReportSubProjects(project_id, mainProject['name'])
        customer = self.getCustomerById(cursor, mainProject['customerId'])

        projects =[mainProject,]
        projects.extend(subProjects)

        for project in projects:
            pId = '%s' % project['id']
            reportData[pId] = {'name':project['name'],'users':{}}
            reportData[pId]['log_hours'] = 0
            reportData[pId]['ticket_hours'] = 0
            reportData[pId]['total_hours'] = 0
            reportData[pId]['budget_hours'] = project['budget']
            reportData[pId]['remaining_hours'] = 0
            #get data from logs
            logEntries = self.getProjectLogs(cursor, project['id'],start_month,start_year, end_month, end_year)
            # entry = {'log_entry_id', 'log_id', 'project_id', 'user_id', 'log_date', 'hours', 'notes'}
            for entry in logEntries:
                uId = '%s' % entry['user_id']
                log_date = entry['log_date']
                if uId not in reportData[pId]['users']:
                    reportData[pId]['users'][uId] = {'user_log_hours':0,'user_ticket_hours':0,'user_total_hours':0,'dates':{},'tickets':{},}
                if entry['notes'] == '':
                    entry['notes'] = "* No Comments"
                if log_date not in reportData[pId]['users'][uId]['dates']:
                    week = str(log_date.isocalendar()[1])
                    if week == "53":
                        week = "0"
                    year = str(log_date.year) 
                    url = base_url + '/edit/' + uId + '/' + year + '/'+ week + '#' + str(log_date)
                    logData = []
                    reportData[pId]['users'][uId]['dates'][log_date] = [url,logData]
                reportData[pId]['users'][uId]['dates'][log_date][1].append([entry['notes'], entry['hours']])
                reportData[pId]['log_hours'] += float(entry['hours'])
                reportData[pId]['users'][uId]['user_log_hours'] += float(entry['hours']) 
                reportData[pId]['users'][uId]['user_total_hours'] += float(entry['hours']) 
            
            #get data from ticket_hours
            ticketEntries = self.getTicketLogs(cursor, project['id'], start_month, start_year, end_month, end_year)
            # {"user_id", "ticket_id", "start_time", "ticket_time", "time_comments","ticket_summary"}
            for entry in ticketEntries:
                uId = '%s' % entry['user_id']
                ticketId = '%s' % entry['ticket_id']
                if uId not in reportData[pId]['users']:
                    reportData[pId]['users'][uId] = {'user_log_hours':0,'user_ticket_hours':0,'user_total_hours':0,'dates':{},'tickets':{},}
                if ticketId not in reportData[pId]['users'][uId]['tickets']:
                    reportData[pId]['users'][uId]['tickets'][ticketId] = {'ticket_summary':entry['ticket_summary'],'ticket_time':0,'ticketData':[]}
                if entry['time_comments'] != '':
                    reportData[pId]['users'][uId]['tickets'][ticketId]['ticketData'].append(entry['time_comments'])
                reportData[pId]['users'][uId]['tickets'][ticketId]['ticket_time'] += float(entry['ticket_time'])
                reportData[pId]['users'][uId]['user_ticket_hours'] += float(entry['ticket_time'])
                reportData[pId]['users'][uId]['user_total_hours'] += float(entry['ticket_time']) 
                reportData[pId]['ticket_hours'] += float(entry['ticket_time'])

            reportData[pId]['total_hours'] = reportData[pId]['log_hours'] + reportData[pId]['ticket_hours']
            reportData[pId]['user_count'] = len(reportData[pId]['users']) + 1
            reportData[pId]['remaining_hours'] = reportData[pId]['budget_hours'] - reportData[pId]['total_hours']
            # remove empty projects
            if len(reportData[pId]['users']) == 0:
                del reportData[pId]
         
        data['customer'] = customer
        data['project'] = mainProject
        data['reportData'] = reportData
        data['report_date'] = "%s, %s to %s, %s" % (start_month, start_year, end_month, end_year)
        data["today"] = datetime.date.today()
        data['ticket_url'] = req.href.ticket()
        # self.log.debug("reportData: %r", reportData)
        return 'report_P.html', data,None
    
    def report_U(self,req):
        """
        Handler for User Report requests
        Get list of projects for user and sort by week, include ticket work 
        """
        data = {}
        weeks = []
        reportData = {}
        db = self.env.get_db_cnx()
        cursor = db.cursor()
        
        user = req.args['user']
        start_month = req.args['start_month']
        start_year = req.args['start_year']
        end_month = req.args['end_month']
        end_year = req.args['end_year']

        base_url = req.href.logs()
        data['user'] = user
        reportData = {}

        #get data from logs
        logEntries = self.getUserLogs(cursor,user,start_month,start_year, end_month, end_year)
        # log = {'log_entry_id':row[0], 'log_id': row[1], 'project_id':row[2], 'log_date':row[3], 'hours':row[4], 'notes':row[5]}
        for entry in logEntries:
            log_date = entry['log_date']
            project_id = str(entry['project_id'])
            week = str(log_date.isocalendar()[1])
            if week == "53":
                week = "0"
            if week not in reportData:
                weeks.append(week)
                week_start = str(self.getWeekStart(log_date))
                reportData[week] = {'week_start':week_start,'project_count':1, 'total_hours':0,'ticket_hours':0,'project_hours':0, 'projects':{},}
            if project_id not in reportData[week]['projects']:
                reportData[week]['project_count'] += 1
                proj_ = self.getProjectById(cursor,project_id)
                cust_ = self.getCustomerById(cursor,proj_['customerId'])
                reportData[week]['projects'][project_id] = {'name':proj_['name'],'customer_id':cust_['id'], 'customer_name':cust_['name'],
                                                            'log_hours':0,'ticket_hours':0,'dates':{}, 'tickets':{},}
            if entry['notes'] == '':
                entry['notes'] = "* No Comments"
            if log_date not in reportData[week]['projects'][project_id]['dates']:
                year = str(log_date.year) 
                url = base_url + '/edit/' + user + '/' + year + '/'+ week + '#' + str(log_date)
                logData = []
                reportData[week]['projects'][project_id]['dates'][log_date] = [url,logData]
            
            reportData[week]['projects'][project_id]['dates'][log_date][1].append([entry['notes'], entry['hours']])
            reportData[week]['projects'][project_id]['log_hours'] += float(entry['hours'])
            reportData[week]['project_hours'] += float(entry['hours']) 
            reportData[week]['total_hours'] += float(entry['hours']) 
            
        #get data from ticket_hours
        ticketEntries = self.getUserTicketLogs(cursor, user, start_month, start_year, end_month, end_year)
        # {"project_id", "ticket_id", "start_time", "ticket_time", "time_comments","ticket_summary"}
        #self.log.debug("Ticket E: %r", ticketEntries)
        for entry in ticketEntries:
            project_id = entry['project_id']
            ticketId = '%s' % entry['ticket_id']
            log_date = datetime.date.fromtimestamp(entry['start_time'])
            week = str(log_date.isocalendar()[1])
            if week == "53":
               week = "0"
            if week not in reportData:
                weeks.append(week)
                week_start = self.getWeekStart(log_date)
                reportData[week] = {'week_start':week_start,'project_count':1, 'total_hours':0,'ticket_hours':0,'project_hours':0, 'projects':{},}
                
            if project_id not in reportData[week]['projects']:
                reportData[week]['project_count'] += 1
                if project_id == '0':
                    proj_ = {'name':'none', 'customerId':0, 'id':0} 
                    cust_ = {'name':'none', 'id':0}
                else:
                    proj_ = self.getProjectById(cursor,project_id)
                    cust_ = self.getCustomerById(cursor,proj_['customerId'])
                reportData[week]['projects'][project_id] = {'name':proj_['name'],'customer_id':cust_['id'], 'customer_name':cust_['name'],
                                                            'log_hours':0,'ticket_hours':0,'dates':{}, 'tickets':{},}
            
            if ticketId not in reportData[week]['projects'][project_id]['tickets']:
                reportData[week]['projects'][project_id]['tickets'][ticketId] = {'ticket_summary':entry['ticket_summary'],'ticket_time':0,'ticketData':[]}
            if entry['time_comments'] != '':
                reportData[week]['projects'][project_id]['tickets'][ticketId]['ticketData'].append(entry['time_comments'])
            reportData[week]['projects'][project_id]['tickets'][ticketId]['ticket_time'] += float(entry['ticket_time'])
            reportData[week]['projects'][project_id]['ticket_hours'] += float(entry['ticket_time'])
            reportData[week]['ticket_hours'] += float(entry['ticket_time'])

            reportData[week]['total_hours'] += float(entry['ticket_time'])
       
        weeks.sort() 
        data['weeks'] = weeks 
        data['reportData'] = reportData
        data['report_date'] = "%s, %s and %s, %s" % (start_month, start_year, end_month, end_year)
        data["today"] = datetime.date.today()
        data['ticket_url'] = req.href.ticket()
        # self.log.debug("Weeks : %r", weeks)
        # self.log.debug("reportData: %r", reportData)

        return 'report_U.html', data,None


    def report_B(self, req):
        data = {}
        weeks = []
        reportData = {}
        userData = {}
        dateCodes = {}
        db = self.env.get_db_cnx()
        cursor = db.cursor()

        base_url = req.href.logs()
        start_month = req.args['start_month']
        start_year = req.args['start_year']
        end_month = req.args['end_month']
        end_year = req.args['end_year']

        start = datetime.date(int(start_year), int(start_month),1)
        last_day = calendar.monthrange(int(end_year),int(end_month))[1]
        end = datetime.date(int(end_year), int(end_month),last_day) 
        if end > datetime.date.today():
            end = datetime.date.today()
        one_day = datetime.timedelta(days=1)
        dcursor = copy.deepcopy(start)
        days = []
         
        while dcursor <= end:
            if dcursor.weekday() < 5:
                days.append(dcursor)
            dcursor = dcursor + one_day

        if not isinstance(req.args['users'], list):
                req.args['users'] = [req.args['users']]
        user_req = req.args['users']
 
        awayProject = int(self.config.get('customerProjects','awayProject',0))
        # self.log.debug("Away: %s", awayProject)

        for user_id in user_req:
            userData[user_id] = {}
            logs = {}
            qry = "SELECT l.log_id, l.user_id, l.log_date, le.notes, le.hours, le.project_id FROM logs as l left join log_entries as le on l.log_id=le.log_id"
            where = " WHERE user_id=%s AND log_date>=%s AND log_date<=%s ORDER BY log_date"
            qry += where 
            vars = (user_id, '%s-%s-01' % (start_year, start_month), '%s-%s-31' % (end_year, end_month))
            cursor.execute(qry,vars)
            rows = cursor.fetchall()
            l_log_id, l_user_id, l_log_date, l_notes, l_hours, l_project_id  = 0,1,2,3,4,5
            for row in rows:
               # self.log.debug("Found Row: %s", row)
               date = row[l_log_date]
               if date not in logs or logs[date][0] == "":
                   #self.log.debug("log date: %s",date)
                   logs[date] = [row[l_notes], row[l_hours], row[l_project_id]]
            ticketEntries = self.getUserTicketLogs(cursor, user_id, start_month, start_year, end_month, end_year)
            # {"project_id", "ticket_id", "start_time", "ticket_time", "time_comments","ticket_summary"}
            #self.log.debug("Ticket E: %r", ticketEntries)
            for entry in ticketEntries:
                log_date = datetime.date.fromtimestamp(entry['start_time'])
                #self.log.debug("Ticket date: %s", log_date)
                if log_date not in logs or (logs[log_date][1] == 0 or logs[log_date][0] == ""):
                    logs[log_date] = [entry['time_comments'],entry['ticket_time'],entry['project_id']]
            missing = []
            for date in days:
                if date not in logs or ((logs[date][1] == 0 or logs[date][0] == "") and int(logs[date][2]) != awayProject):
                    year = str(date.year)
                    week = str(date.isocalendar()[1])
                    if week == "53":
                        week = "0"
                    dateCode = year + '/' + week +'#' + str(date)
                    missing.append(date)
                    if date not in dateCodes:
                        dateCodes[date] = dateCode
                    # self.log.debug("Missing date : %r", date)
            userData[user_id] = missing

        dateUrl = base_url + '/edit/' + user_id + '/' 
        data['report_date'] = "%s and %s" % (start, end)
        data['base_url'] = base_url
        data['userData'] = userData
        data['dateCodes'] = dateCodes
        return 'report_B.html',data,None

    def edit(self, req):
        """
        Handler for the page for users to edit their logs
        """
        data = {}
        logs = {}
        t_logs = {}
        errors = []
        days = []
        dayNames = {}
        qry_dbg = ""
        (action, user_id, year, curWeek) = req.args['rest'].split("/")
        db = self.env.get_db_cnx() 
        cursor = db.cursor() 

        data['user_name'] = user_id
        # data['projects'] = projects       
        customers = self.getCustomers(cursor)
        data['customers'] = customers
        data['default_customer'] = str(self.getDefaultCustomerId(cursor, user_id))
        # sortedprojects = projects.items()
        # sortedprojects.sort()
        (weeks, tmp) = self.getWeeks(year)
        data['weeks'] = weeks
        data['weekNums'] = range(0,len(weeks)) 
        curYear = datetime.date(int(year),1,1).year
        data['years'] = range(2007, datetime.date.today().year + 2)
        data['year'] = curYear
        data['week'] = str(weeks[int(curWeek)])
        data['hours'] = ['0'+str(h) for h in range(0,10)]+[str(h) for h in range(10,24)]
        # [str(h) for h in range(0,24)]
        data['extra_hours'] = [str(float(t)/float(2)) for t in range(0,49)]
        data['minutes'] = ["00", "15", "30", "45"]
        data['user_id'] = user_id
        for i in range(0,7):
            day = weeks[int(curWeek)] + datetime.timedelta(days=i)
            days.append(str(day))
            dayNames[str(day)] = day.strftime("%A")
            logs[str(day)] = self.getDayInfo(cursor, day, user_id)
            t_logs[str(day)] = self.getTicketDayInfo(cursor, day, user_id)

        anchor = ""    
        for key in req.args.keys():
            value = req.args[key]
            if "RemoveEntry" in key:
                submittedLogs = {}
                self.compilePostData(submittedLogs, req.args)
                logs = submittedLogs
                remove_entry_day = key.split("_")[1]
                anchor = remove_entry_day
                remove_log_entry_id = key.split("_")[2]
                entries = logs[remove_entry_day]['entries']
                del entries[remove_log_entry_id]
            if "AddEntry" in key:
                submittedLogs = {}
                self.compilePostData(submittedLogs, req.args)
                logs = submittedLogs
                add_entry_day = key.split("_")[1]
                anchor = add_entry_day
                entries = logs[add_entry_day]['entries']
                newKey = self.findMin(entries.keys())
                entries[newKey] = {}
                entries[newKey]["project_id"] = req.args['NewEntryProject_%s' % add_entry_day]
                entries[newKey]["customer_id"] = req.args['NewEntryCustomer_%s' % add_entry_day]
                entries[newKey]["hours"] = 0
                entries[newKey]["notes"] = ""
                entries[newKey]["log_entry_id"] = newKey
        if "save" in req.args:
            submittedLogs = {}
            self.compilePostData(submittedLogs, req.args)
            #self.log.debug("Sub Log: %r", submittedLogs)
            if submittedLogs.has_key('tickets'):
                tickets = submittedLogs['tickets']
                del submittedLogs['tickets']
                # self.log.debug("Updated Tickets: %r: " , tickets)
                up_tickets = []
                for day in tickets.keys():
                    # self.log.debug(" Day: %s" , day)
                    # self.log.debug("Tickets: %r " , tickets[str(day)]) 
                    for t_id, t_data in tickets[str(day)].items():
                        # self.log.debug("ID: %s", t_id)
                        if t_data['time_comments'] != t_logs[str(day)][str(t_id)]['time_comments'] or t_data['ticket_time'] != t_logs[str(day)][str(t_id)]['ticket_time']:
                            up_tickets.append((t_id, t_data))
                            t_logs[str(day)][str(t_id)]['time_comments'] = t_data['time_comments']
                            t_logs[str(day)][str(t_id)]['ticket_time'] = t_data['ticket_time']
                if len(up_tickets) > 0:
                    self.updateTickets(up_tickets)

            for day in submittedLogs.keys():
                if submittedLogs[day] != logs[day]:
                    if self.checkForErrors(submittedLogs[day], errors):
                        # self.log.debug("sub: %r", submittedLogs[day] )
                        # self.log.debug("logs %r", logs[day])
                        queries = self.updateDatabase(day, submittedLogs[day])
                        logs[day] = self.getDayInfo(cursor, day, user_id)
                    else:
                        qry_dbg = str(submittedLogs[day]) + "-----" + str(logs[day])
                        logs[day] = submittedLogs[day]
                    qry_dbg = qry_dbg + "||".join(queries)
        else:
            submittedLogs = {}
        data['days'] = days
        data['dayNames'] = dayNames
        data['logs'] = logs         
        data['t_logs'] = t_logs         
        data['qry_dbg'] = qry_dbg
        data['error_msg'] = "\n".join(errors)
        data['keys'] = ",".join(logs.keys())
        data['test_output'] = "Not Found"
        data['anchor'] = anchor
        data['p_base_url'] = req.href.c_projects()
        data['t_base_url'] = req.href.ticket()
        for these_logs in submittedLogs.keys():
            if 'entries' not in submittedLogs[these_logs].keys():
                data['test_output'] = "Found: " + these_logs
                
        add_script(req, 'logs/js/logs.js')
        return 'edit.html', data, None

    # ITemplateProvider methods
    def get_templates_dirs(self):
        """Return a list of directories containing the provided ClearSilver
        templates.
        """
        from pkg_resources import resource_filename
        return [resource_filename(__name__, 'templates')]
    
    def get_htdocs_dirs(self):
        """Return a list of directories with static resources (such as style
        sheets, images, etc.)

        Each item in the list must be a `(prefix, abspath)` tuple. The
        `prefix` part defines the path in the URL that requests to these
        resources are prefixed with.

        The `abspath` is the absolute path to the directory containing the
        resources on the local file system.
        """
        from pkg_resources import resource_filename
        return [('logs', resource_filename(__name__, 'htdocs'))]

    #Utility functions
    def getWeeks(self, year=None):
        """
        Returns a list of date objects, with each date being the start of a week.  The list contains all the week
        beginnings for the current year.  Also returns the index of the current week in the list.
        """
        today = None 
        if year is None: 
            # self.log.info("Year was none")
            today = datetime.date.today() 
            year = today.year 
            # self.log.info("Year is now %s and today is %s" % (str(year), str(today)))
            curWeek = today.isocalendar()[1]
        else:
            curWeek = 0
        year = int(year) 
        cursor = datetime.date(year, 1, 1)
        one_day = datetime.timedelta(days = 1)

        weeks = [cursor]
        #Iterate through the days of this year
        while cursor.year == year:
            cursor = cursor + one_day
            if cursor.weekday() == 0:
                #self.log.info("Cursor: %s" % str(cursor))
                weeks.append(cursor)
            #if today is not None: 
                # self.log.info("Checking stuff: %s %s, %s %s" % (str(cursor.day), str(today.day), str(cursor.month), str(today.month)))
            #    if cursor.day == today.day and cursor.month == today.month: 
                    # self.log.info("Found curWeek")
            #        curWeek = len(weeks)-1 
            #else: 
            #    curWeek = 0
        return (weeks, curWeek)

    def getWeekStart(self, actualDate):
        """
        Returns a datetime object representing the first day (the Monday, in this case) of the week
        which actualDate is part of (actualDate is also a datetime object)
        """
        dow = actualDate.weekday()
        monday = actualDate - datetime.timedelta(days = dow)
        return monday
        
    def getProjectByTicketId(self, cursor, ticket_id):
        """
        return project for ticket by ticket id
        """
        qry = "SELECT id, parentId, customerId, name, active, workon, budget from c_projects where id = (select value from ticket_custom where name='project' and ticket=%s)" % ticket_id
        cursor.execute(qry)
        row = cursor.fetchone()
        if row == None:
            proj = {'id':0, 'parentId':0, 'customerId':0, 'name':'', 'active':0, 'workon':0, 'budget':0,} 
        else:
            proj = {'id':row[0], 'parentId':row[1], 'customerId':row[2], 'name':row[3], 'active':row[4], 'workon':row[5], 'budget':row[6],} 
        return proj

    def getProjectById(self, cursor, project):
        """
        return project details for project id
        """
        qry = "SELECT id, parentId, customerId, name, active, workon, budget from c_projects where id = %s"
        cursor.execute(qry,[project,])
        row = cursor.fetchone()
        proj = {'id':row[0], 'parentId':row[1], 'customerId':row[2], 'name':row[3], 'active':row[4], 'workon':row[5], 'budget':row[6],} 
        return proj
    
    def getCustomerById(self, cursor, customer):
        """
        return customer name for customer id
        """
        qry = "SELECT id, name, data  from customers where id = %s"
        cursor.execute(qry,[customer,])
        row = cursor.fetchone()
        cust = {'id':row[0], 'name':row[1], 'data':row[2]}
        return cust

    def getCustomers(self, cursor):
        """ 
        Returns dictionary of customers
        """
        qry = "SELECT id, name, data from customers order by name"
        cursor.execute(qry)
        rows = cursor.fetchall()
        customers = []
        for row in rows:
            cust = {'id': row[0],  'name' : row[1], 'data' : row[2]}
            customers.append(cust)
        return customers

    def getUserTicketLogs(self, cursor, user, start_month, start_year, end_month, end_year):
        """
        returns dictionary of ticket log entries (ticket #, ticket summary, time, notes)
        """
        start_time = datetime.date(int(start_year), int(start_month), 1)
        last_day = calendar.monthrange(int(end_year),int(end_month))[1]
        end_time = datetime.date(int(end_year), int(end_month), last_day)

        start_day_seconds = int(time.mktime(start_time.timetuple()))
        end_day_seconds =  int(time.mktime(end_time.timetuple())) + 86399
        qry = "SELECT tt.ticket, tt.time_started, tt.seconds_worked, tt.comments, tc.value, (select summary from ticket where id = tt.ticket) from ticket_time as tt left join ticket_custom as tc on tt.ticket = tc.ticket" 
        where = " where tt.worker=%s "
        where += " and tc.name='project' " 
        where += " and tt.time_started between %s and %s "
        order = " order by tt.time_started "
        qry = qry + where + order
        vars = (user, start_day_seconds, end_day_seconds)
        q_ticket_id, q_start_time, q_seconds_worked, q_comments, q_project_id, q_summary = 0,1,2,3,4,5
        ticket_list = []
        cursor.execute(qry,vars)
        rows = cursor.fetchall()
        for row in rows:
            ticket_ = {"project_id": row[q_project_id], "ticket_id": row[q_ticket_id], "start_time": row[q_start_time], "ticket_time":float(row[q_seconds_worked])/3600, "time_comments":row[q_comments],"ticket_summary":row[q_summary]}
            ticket_list.append(ticket_)
        return ticket_list

    def getTicketLogs(self, cursor, project, start_month, start_year, end_month, end_year):
        """
        returns dictionary of ticket log entries (ticket #, ticket summary, time, notes)
        """
        if start_month == 'ALL':
            start_time = datetime.date(int(start_year), 1, 1)
            last_day = 31
            end_time = datetime.date(int(start_year), 12, last_day)
        else:
            start_time = datetime.date(int(start_year), int(start_month), 1)
            last_day = calendar.monthrange(int(end_year),int(end_month))[1]
            end_time = datetime.date(int(end_year), int(end_month), last_day)

        start_day_seconds = int(time.mktime(start_time.timetuple()))
        end_day_seconds =  int(time.mktime(end_time.timetuple())) + 86399
        qry = "SELECT tt.ticket, tt.time_started, tt.seconds_worked, tt.comments, tt.worker, (select summary from ticket where id = tt.ticket) from ticket_time as tt left join ticket_custom as tc on tt.ticket = tc.ticket "
        where = " where tc.value=%s "
        where += " and tc.name='project' "
        where += " and tt.time_started between %s and %s "
        order = " order by tt.time_started "
        qry = qry + where + order
        vars = (project, start_day_seconds, end_day_seconds)
        q_ticket_id, q_start_time, q_seconds_worked, q_comments, q_user_id, q_summary = 0,1,2,3,4,5
        ticket_list = []
        cursor.execute(qry,vars)
        rows = cursor.fetchall()
        for row in rows:
            ticket_ = {"user_id": row[q_user_id], "ticket_id": row[q_ticket_id], "start_time": row[q_start_time], "ticket_time":float(row[q_seconds_worked])/3600, "time_comments":row[q_comments],"ticket_summary":row[q_summary]}
            ticket_list.append(ticket_)
        return ticket_list

    def getProjectLogs(self, cursor, project, start_month, start_year, end_month, end_year):
        """
        returns list of project logs for project during time
        """
        if start_month == 'ALL':
            start_time = "%s-01-01" % (start_year)
            end_time = "%s-12-31" % (start_year)
        else:
            start_time = "%s-%s-01" % (start_year, start_month) 
            end_time = "%s-%s-31" % (end_year, end_month)
        
        qry = "select le.log_entry_id, le.log_id, le.project_id, l.user_id, l.log_date, le.hours, le.notes from log_entries as le join logs as l on le.log_id = l.log_id"
        where = " where l.log_date between '%s' and '%s' " % (start_time, end_time)
        where += " and le.project_id = %s" % project
        where += " and le.hours > 0 " 
        order = " order by l.log_date "
        qry = qry + where + order
        cursor.execute(qry)
        rows = cursor.fetchall()
        projectLogs = []
        for row in rows:
            log = {'log_entry_id':row[0], 'log_id': row[1], 'project_id':row[2], 'user_id':row[3], 'log_date':row[4], 'hours':row[5], 'notes':row[6]}
            projectLogs.append(log)
        return projectLogs

    def getUserLogs(self, cursor, user, start_month, start_year, end_month, end_year):
        """
        returns list of project logs for project during time
        """
        start_time = "%s-%s-01" % (start_year,start_month)
        end_time = "%s-%s-31" % (end_year,end_month)
       
        qry = "select le.log_entry_id, le.log_id, le.project_id, l.log_date, le.hours, le.notes from log_entries as le join logs as l on le.log_id = l.log_id"
        where = " where l.user_id = '%s'" % user
        where += "  and l.log_date between '%s' and '%s' " % (start_time, end_time)
        where += " and le.hours > 0 " 
        order = " order by l.log_date "
        qry = qry + where + order
        cursor.execute(qry)
        rows = cursor.fetchall()
        userLogs = []
        for row in rows:
            log = {'log_entry_id':row[0], 'log_id': row[1], 'project_id':row[2], 'log_date':row[3], 'hours':row[4], 'notes':row[5]}
            userLogs.append(log)
        return userLogs

    def getSubProjects(self, project_id,spacer='>'):
        """
        Returns list of subprojects for project
        """
        spacer = '--' + spacer
        db = self.env.get_db_cnx()
        cursor = db.cursor()
        qry = "SELECT id, parentId, customerId, name, active, workon, budget from c_projects where parentId = %s"
        cursor.execute(qry,[project_id,])
        rows = cursor.fetchall()
        subProjects = []
        for row in rows:
            proj = {'id':row[0], 'parentId':row[1], 'customerId':row[2], 'name':spacer+row[3], 'active':row[4], 'workon':row[5], 'budget':row[6],} 
            subProjects.append(proj)
            sub2 = self.getSubProjects(row[0],'+' + spacer)
            subProjects.extend(sub2)
        return subProjects

    def getReportSubProjects(self, project_id,parentName):
        """
        Returns list of subprojects for project
        """
        spacer = '/'
        db = self.env.get_db_cnx()
        cursor = db.cursor()
        qry = "SELECT id, parentId, customerId, name, active, workon, budget from c_projects where parentId = %s"
        cursor.execute(qry,[project_id,])
        rows = cursor.fetchall()
        subProjects = []
        for row in rows:
            new_name = parentName + spacer + row[3]
            proj = {'id':row[0], 'parentId':row[1], 'customerId':row[2], 'name':new_name, 'active':row[4], 'workon':row[5], 'budget':row[6],} 
            subProjects.append(proj)
            sub2 = self.getReportSubProjects(row[0],new_name)
            subProjects.extend(sub2)
        return subProjects

    def getProjects(self, cursor, customer=0):
        """
        returns list of projects for customer
        """
        qry = "SELECT id, parentId, customerId, name, active, workon, budget from c_projects "
        if customer:
            qry += " where customerId = %s" % customer
        cursor.execute(qry)
        rows = cursor.fetchall()
        projects = []
        for row in rows:
            proj = {'id':row[0], 'parentId':row[1], 'customerId':row[2], 'name':row[3], 'active':row[4], 'workon':row[5], 'budget':row[6],} 
            projects.append(proj)
        return projects
    
    def getParentProjects(self, cursor, customer=0):
        """
        returns list of Parent Projects for customer
        """
        qry = "SELECT id, parentId, customerId, name, active, workon, budget from c_projects where parentId = 0"
        if customer:
            qry += " and customerId = %s" % customer
        cursor.execute(qry)
        rows = cursor.fetchall()
        projects = []
        for row in rows:
            proj = {'id':row[0], 'parentId':row[1], 'customerId':row[2], 'name':row[3], 'active':row[4], 'workon':row[5], 'budget':row[6],} 
            projects.append(proj)
        return projects

    
    def getDefaultProjectId(self, cursor, user_id):
        """
        Returns the id of the default project for the given user.  Returns -1 if the user does not have a
        default project.
        """
        return self.config.get('customerProjects','defaultProject',0)
        #TODO: Setup a shadow table to track user data like this (or maybe stick it in the user preferences?)
        qry = "SELECT default_project_id FROM users WHERE user_id='%s'" % user_id
        cursor.execute(qry)
        rows = cursor.fetchall()
        if len(rows) == 0:
            return -1;
        else:
            return rows[0]['default_project_id']
    
    def getDefaultCustomerId(self, cursor, user_id):
        """
        Returns the id of the default project for the given user.  Returns -1 if the user does not have a
        default project.
        """
        return self.config.get('customerProjects','defaultCustomer',0)

        #TODO: Setup a shadow table to track user data like this (or maybe stick it in the user preferences?)
        qry = "SELECT default_project_id FROM users WHERE user_id='%s'" % user_id
        cursor.execute(qry)
        rows = cursor.fetchall()
        if len(rows) == 0:
            return -1;
        else:
            return rows[0]['default_project_id']

    def getTicketDayInfo(self, cursor, day, user_id):
        """
        Returns a dictionary containing all the ticket data for one day. 
        """
        # convert day to seconds
        # self.log.debug("Day %r" , day)
        start_day_seconds = int(time.mktime(day.timetuple()))
        end_day_seconds =  start_day_seconds + 86399
        qry = "SELECT tt.id, tt.ticket, tt.seconds_worked, tt.comments, t.summary from ticket_time as tt left join ticket as t on tt.ticket = t.id"
        where = " where tt.worker = %s "
        where += " and tt.time_started between %s and %s "
        qry = qry + where
        vars = (user_id, start_day_seconds, end_day_seconds)
        q_id, q_ticket, q_seconds_worked, q_comments, q_summary = 0,1,2,3,4
        ticket_list = {}
        cursor.execute(qry,vars)
        rows = cursor.fetchall()
        for row in rows:
            project = self.getProjectByTicketId(cursor,row[q_ticket])
            ticket_list['%s'%row[q_id]] = {"ticket_id": row[q_ticket], "ticket_time":float(row[q_seconds_worked])/3600, "time_comments":row[q_comments],"ticket_summary":row[q_summary],
                                            "project_id":project['id'], 'project_name':project['name']}
        return ticket_list

    def getDayInfo(self, cursor, day, user_id):
        """
        Returns a dictionary containing all the data for one day.  Comes from the database if the data is there,
        otherwise it is set to defaults
        """
        qry = "SELECT * FROM logs WHERE log_date='%s' AND user_id='%s' order by log_date " % (str(day), user_id)
        cursor.execute(qry)
        row = cursor.fetchone()
        data = {}
        data["user_id"] = user_id
        if row is None:
            data["log_id"] = -1
            data["start_hour"] = "00"
            data["start_minute"] = "00"
            data["stop_hour"] = "0"
            data["stop_minute"] = "00"
            data["extra"] = "0.0"
            data["entries"] = {}
            #Because this isn't actually in the database yet, we'll put in a fake log_entry_id
            data["entries"][-1] = {}
            data["entries"][-1]["project_id"] = str(self.config.get('customerProjects','awayProject',0))
            data["entries"][-1]["customer_id"] = str(self.getDefaultCustomerId(cursor, user_id))
            data["entries"][-1]["hours"] = 0
            data["entries"][-1]["notes"] = ""
            data["entries"][-1]["log_entry_id"] = -1
            
            data["entries"][-2] = {}
            data["entries"][-2]["project_id"] = str(self.getDefaultProjectId(cursor, user_id))
            data["entries"][-2]["customer_id"] = str(self.getDefaultCustomerId(cursor, user_id))  
            data["entries"][-2]["hours"] = 0
            data["entries"][-2]["notes"] = ""
            data["entries"][-2]["log_entry_id"] = -2
        else:
            start = str(row[3]).split(":")
            stop = str(row[4]).split(":")
            # self.log.debug("Start hour %s", start[0])
            # self.log.debug("Stop %s", stop)
            data["start_hour"] = str(start[0])
            data["start_minute"] = str(start[1])
            data["stop_hour"] = str(stop[0])
            data["stop_minute"] = str(stop[1])
            data["extra"] = str(row[5])
            data["log_id"] = str(row[0])
            data["entries"] = {}
            qry = "select log_entry_id, log_id, project_id, hours, notes, customerId from log_entries as l join c_projects as cp on l.project_id = cp.id where log_id='%s' order by log_entry_id" % row[0]
            # qry = "SELECT * FROM log_entries WHERE log_id='%s'" % row[0]
            cursor.execute(qry)
            entries = cursor.fetchall()
            for entry in entries:
                data["entries"][str(entry[0])] = {}
                data["entries"][str(entry[0])]["project_id"] = str(entry[2])
                data["entries"][str(entry[0])]["hours"] = str(float(entry[3]))
                data["entries"][str(entry[0])]["notes"] = entry[4]
                data["entries"][str(entry[0])]["log_entry_id"] = str(entry[0])
                data["entries"][str(entry[0])]["customer_id"] = str(entry[5])
            if len(entries) == 0:
                data["entries"]["-1"] = {}
                data["entries"]["-1"]["project_id"] = str(self.getDefaultProjectId(cursor, user_id))
                data["entries"]["-1"]["customer_id"] = str(self.getDefaultCustomerId(cursor, user_id))
                data["entries"]["-1"]["hours"] ="0"
                data["entries"]["-1"]["notes"] = ""
                data["entries"]["-1"]["log_entry_id"] = "-1"
        return data

    def compilePostData(self, logs, args):
        """
        In the html, form inputs have names like logs['1']['extra_hours'] which mimic the syntax for a python dictionary.
        When the form is submitted however, the submitted variables are strings of the form "logs['1']['extra_hours']", rather than
        dictionaries since the trac framework doesn't roll like that.  So, this function examines the names of the submitted form
        inputs, and if they look like dictionary syntax then they are put into the logs dictionary and the value in the dictionary is
        set to the value of the submitted form input.  There's some trickiness because we have nested dictionaries and we might process
        an entry in a dictionary that doesn't exist yet, so we have to make sure all the parent dictionaries are created first
        """
        pat = re.compile(r"\[(.*?)\]")
        for var in args.keys():
            if "[" in var and "]" in var:
                matches = re.findall(pat, var)
                curDict = logs
                for key in matches[:-1]:
                    key = key.replace("'", "")
                    if key not in curDict:
                        curDict[key] = {}
                    curDict = curDict[key]
                matches[-1] = matches[-1].replace("'", "")
                curDict[matches[-1]] = args[var]

    def updateTickets(self, tickets):
        """
        updates the ticket time and comments for tickets
        """
        dbConn = self.env.get_db_cnx()
        cursor = dbConn.cursor()
        qry = "Update ticket_time set comments=%s, seconds_worked=%s where id=%s"
        for id, data in tickets:
            comment = data['time_comments']
            hours = data['ticket_time']
            seconds = float(hours) * 3600
            vars = (comment, seconds, id)
            cursor.execute(qry,vars)
        dbConn.commit()

    def updateDatabase(self, day, logs):
        """
        Goes through one days worth of the logs dictionary and either updates rows in the database or inserts new rows
        If a row has an id that is less than 0, it is assumed that it was created by the app and does not yet exist in
        the database.  If the id is 0 or greater then it's assumed that the entry already exists in the database and just
        needs to be updated.
        
        day is a string representation of the date to be updated
        logs is a dictionary containing all the necessary fields for that day
        dbConn is a python database connection, used for string escaping
        cursor is a python database cursor
        """
        updated = datetime.datetime.now()
        updated = '%s' % updated

        dbConn = self.env.get_db_cnx() 
        cursor = dbConn.cursor()
        queries = []
        vars = (logs["user_id"], day, "%s:%s" % (logs['start_hour'],logs['start_minute']), "%s:%s" % (logs['stop_hour'], logs['stop_minute']), logs['extra'], updated)
        if int(logs["log_id"]) >= 0:
            qry = "UPDATE logs set user_id = %s, log_date = %s, start=%s, end = %s, extra=%s, updated=%s WHERE log_id=%s"
            exec_vars = vars+(logs["log_id"],)
            cursor.execute(qry, exec_vars)
            dbConn.commit()
        else:
            qry = """INSERT INTO logs (user_id, log_date, start, end, extra, updated) VALUES (%s, %s, %s, %s, %s, %s)"""
            # print qry
            cursor.execute(qry,vars)
            logs["log_id"] = cursor.lastrowid
            dbConn.commit()
        queries.append(qry)

        for (log_entry_id, entry) in logs['entries'].items():
            qry_data = "(log_id, project_id, hours, notes, updated) VALUES (%s, %s, %s, %s, %s)"
            vars = (logs["log_id"], entry["project_id"], entry["hours"], entry["notes"], updated)
            if log_entry_id != '' and int(log_entry_id) >= 0:
                qry = "UPDATE log_entries set log_id =%s, project_id =%s, hours = %s, notes = %s, updated=%s WHERE log_entry_id=%s"
                exec_vars = vars+(log_entry_id,)
                qry_e = qry % exec_vars
                cursor.execute(qry, exec_vars)
                logs['entries'][str(log_entry_id)] = entry
                dbConn.commit()
            else:
                qry = "INSERT INTO log_entries %s" % qry_data
                vars = (logs["log_id"], entry["project_id"], entry["hours"], entry["notes"], updated)
                cursor.execute(qry, vars)
                entry['log_entry_id'] = cursor.lastrowid
                logs['entries'][str(cursor.lastrowid)] = entry
                dbConn.commit()
            queries.append(qry)

        qry = "SELECT log_entry_id FROM log_entries WHERE log_id='%s'" % logs["log_id"]
        cursor.execute(qry)
        rows = cursor.fetchall()
        for row in rows:
            if str(row[0]) not in logs['entries'].keys():
                qry = "DELETE FROM log_entries WHERE log_entry_id='%s'" % row[0]
                queries.append(qry)
                cursor.execute(qry)
                dbConn.commit()
        # print logs
        logs = self.getDayInfo(cursor, day, logs["user_id"])

        return queries

    def checkForErrors(self, logs, errorList):
        if (int(logs["start_hour"]) > int(logs["stop_hour"]) and int(logs["stop_hour"]) > 0) :
            errorList.append("Start hour is later than the stop hour.")
            return False
        return True

    def findMin(self, values):
        """
        Returns the next smallest negative number based on the numbers in values (i.e. if 
        values is [1,5,6,-1], this would return -2)
        """
        values = [int(t) for t in values]
        if min(values) > 0:
            return -1
        else:
            return min(values) - 1
