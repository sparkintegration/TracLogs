TracLogs
========

A plugin to manage daily logs and create reports against customers and projects.

Dependencies
------------

* CustProj - https://github.com/sparkintegration/CustProj
* FeedParser (pip install FeedParser)
* ComponentDependencyPlugin - http://trac-hacks.org/wiki/ComponentDependencyPlugin
* TicketSidebarProviderPlugin - http://trac-hacks.org/wiki/TicketSidebarProviderPlugin
* TracHoursPlugin - http://trac-hacks.org/wiki/TracHoursPlugin
* TracSqlHelperScript - http://trac-hacks.org/wiki/TracSqlHelperScript

Installation
------------

Install as usual, then upgrade environment (i.e. trac-admin <trac env> upgrade).    
    
If your installation is not located at http://host/trac, htodcs/js/logs.js must be edited so that the getJSON call contains the correct URL.