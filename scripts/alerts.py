import ConfigParser
import sys
import datetime
import MySQLdb
import smtplib

def setup_db(config):
    database = config.get('database', 'database')
    host = config.get('database', 'host')
    password = config.get('database', 'password')
    user = config.get('database', 'user')
    conn = MySQLdb.connect (host = host,
                           user = user,
                           passwd = password,
                           db = database)
    return conn

def check_missing(db, user, date):
    print "Checking %s for %s" % (user, date)
    cursor = db.cursor()
    logs = {}
    qry = "SELECT l.log_id, l.user_id, l.log_date, le.notes, le.hours, le.project_id FROM logs as l left join log_entries as le on l.log_id=le.log_id"
    where = " WHERE user_id=%s AND log_date=%s"
    qry += where
    vars = (user, '%s-%s-%s' % (date.year, date.month, date.day))
    cursor.execute(qry,vars)
    rows = cursor.fetchall()
    l_log_id, l_user_id, l_log_date, l_notes, l_hours, l_project_id  = range(6)
    for row in rows:
       print "Found Row: %s" % (row,)
       date = row[l_log_date]
       if date not in logs or logs[date][0] == "":
           #self.log.debug("log date: %s",date)
           logs[date] = [row[l_notes], row[l_hours], row[l_project_id]]
    missing = []
    if date not in logs or ((logs[date][1] == 0 or logs[date][0] == "")):
        year = str(date.year)
        week = str(date.isocalendar()[1])
        if week == "53":
            week = "0"
        missing.append(date)
        # self.log.debug("Missing date : %r", date)
    return len(missing) > 0

def send_email(config, user, date):
    from_addr = config.get('email', 'from')
    domain = config.get('email', 'domain')
    url = config.get('email', 'url')
    msg = """From: Trac Logs <%s>
To: %s@%s
Subject: [Missing Logs] Logs missing for %s

Your logs for today are missing. Please visit %s/logs/edit/%s/%s/%s to complete them.

--

To disable or change the timing of this alert, please contact %s
    """ % (from_addr, user, domain, date, url, user, date.year, date.isocalendar()[1], from_addr)
    server = smtplib.SMTP(config.get('email', 'smtp_server'))
    server.sendmail(from_addr, ["%s@%s" % (user, domain)], msg)
    server.quit()

def check_logs(config, db):
    current_time = datetime.datetime.now().time()
    for user in config.options('users'):
        alert_time_str = config.get('users', user)
        alert_time = datetime.time(*[int(i) for i in alert_time_str.split(":")])
        date = datetime.datetime.now().date()
        if current_time.hour == alert_time.hour and date.weekday():
            missing = check_missing(db, user, date)
            if missing:
                print "alert!"
                send_email(config, user, date)

def main(args):
    config = ConfigParser.RawConfigParser()
    if len(args) > 1:
        config_file = args[1]
    else:
        config_file = 'alerts.cfg'
    config.read(config_file)
    db = setup_db(config)
    check_logs(config, db)
    return 0

if __name__=="__main__":
    sys.exit(main(sys.argv))