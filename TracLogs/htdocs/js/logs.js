function updateProjects_a(){
    ($(this)).updateProjects();
    }

(function($){
        var cache = {};
        
        jQuery.fn.updateProjects = function() { 
        return this.each(function() { 
        
        var customer_dropdown = jQuery(this);
        var no_dis = customer_dropdown.attr('no_dis');
        var p_id = customer_dropdown.attr('p_id');
        var project_dropdown = $("#"+escapeStr(p_id) );
        var custId = customer_dropdown.val();
        var projectId = project_dropdown.val();
        var selected = 0;
        var candidate = 0;

        command = 'list';
        pid = 0, name = 1, workon = 2, active = 3;
        if (custId)
        {
            if (cache[custId])
            { 
                project_dropdown.html("");
                for (key in cache[custId])
                { 
                dis = '',dis_t = '', inactive = '';
                if (cache[custId][key][workon] == 0)
                    { dis_t = ' * ';
                      if (no_dis != 1)
                        { dis = 'disabled=1'; }
                    }
                if (cache[custId][key][active] == 0)
                    inactive = " (inactive) ";
                if (projectId == cache[custId][key][pid])
                    {
                        $("<option value='" + cache[custId][key][pid] + "' selected='selected'>" + cache[custId][key][name] + dis_t + inactive + "</option>").appendTo("#" + escapeStr(p_id));
                        selected = cache[custId][key][pid];    
                    }
                else
                    {
                    $("<option value='" + cache[custId][key][pid] + "'" + dis + ">" + cache[custId][key][name] + "</option>").appendTo("#" + escapeStr(p_id));
                    if ((dis == '') && (candidate == 0))
                        candidate = cache[custId][key][pid]
                    }
                }
                // set selected
                if (selected == 0)
                    $("#" + escapeStr(p_id) + " option[value='"+candidate+"']").attr('selected','selected');
            }
            else
            {

            $.ajax({  
                url: '/trac/cust/' + command + '/' + custId,  
                dataType: 'json',  
                async: false,  
                success: (function(p_id, custId, projectId) { 
                    return function(data) {
                    project_dropdown.html("");
                    cache[custId] = {};
                    $.each(data, function(id, value) {
                        cache[custId][id] = value;
                        dis = '',dis_t = '', inactive = '';
                        if (value[workon] == 0)
                            { dis_t = ' * ';
                              if (no_dis != 1)
                                { dis = 'disabled=1'; }
                         }
                        if (value[active] == 0)
                              inactive = ' (inactive) ';
                        if  (projectId == value[pid])
                            {   selected = value[pid];
                                $("<option value='"+value[pid]+"' selected='selected'>"+value[name] + dis_t +inactive + "</option>").appendTo("#" + escapeStr(p_id)); 
                            }
                        else
                            { 
                             $("<option value='"+value[pid]+"'" + dis + ">"+value[name]+"</option>").appendTo("#" + escapeStr(p_id));
                             if ((candidate == 0) && (dis == ''))
                                candidate = value[pid]
                            }
                        });
                    }
                })(p_id,custId,projectId)
            });
            if (selected == 0)
                $("#" + escapeStr(p_id) + " option[value='"+candidate+"']").attr('selected','selected');
            } 
       }
      });
    };
})(jQuery);

function getElementsByClassName(classname, day, node)  {
    if(!node) node = document.getElementsByTagName("body")[0];
    var a = [];
    var re = new RegExp('\\b' + classname + '\\b');
    var els = node.getElementsByTagName("*");
    for(var i=0,j=els.length; i<j; i++)
        
    if(re.test(els[i].className) && els[i].name.indexOf(day) > 0)
    {
        a.push(els[i]);   
    }
    return a;
}

function setTotalTimes(day)
{
    startTimeHour = document.getElementById("logs['" + day + "']['start_hour']");
    // startTimeHour = $("#logs['" + day + "']['start_hour'] :selected").text();
    startTimeMinute = document.getElementById("logs['" + day + "']['start_minute']");
    // startTimeMinute = $("#logs['" + day + "']['start_minute'] :selected").text();
    stopTimeHour = document.getElementById("logs['" + day + "']['stop_hour']");
    // stopTimeHour = $("#logs['" + day + "']['stop_hour'] :selected").text();
    stopTimeMinute = document.getElementById("logs['" + day + "']['stop_minute']");
    // stopTimeMinute = $("#logs['" + day + "']['stop_minute'] :selected").text();
    extra = document.getElementById("logs['" + day + "']['extra']");
    //extra = $("#logs['" + day + "']['extra'] :selected").text();
    diff = ((stopTimeHour.value - startTimeHour.value) + ((stopTimeMinute.value - startTimeMinute.value)/60)) + parseFloat(extra.value);
    // diff = ((stopTimeHour - startTimeHour) + ((stopTimeMinute - startTimeMinute)/60)) + parseFloat(extra);
    totalWorked = document.getElementById("total_worked['" + day + "']")
    totalWorked.innerHTML = diff;
    
    total = 0;
    entries = getElementsByClassName("entryHour", day)
    for (i in entries)
    {
        iNumber = parseFloat(entries[i].value);
        if (iNumber)
        {   total += iNumber;
            entries[i].value = iNumber;
        }
        else
           entries[i].value = '0.0';
    }
    
    t_total = 0;
    t_entries = getElementsByClassName("ticketHour", day)
    for (i in t_entries)
    {
        tNumber = parseFloat(t_entries[i].value);
        if (tNumber)
        {    t_total += tNumber;
             t_entries[i].value = tNumber;
        }
        else
            t_entries[i].value = '0.0';
    }

    ticketTotal = document.getElementById("ticketTotal['" + day + "']")
    ticketTotal.innerHTML = t_total;
    totalClaimed = document.getElementById("total_claimed['" + day + "']")
    totalClaimed.innerHTML = total + t_total;
    grand_total = total + t_total;

    warningCell = document.getElementById("warning['" + day + "']")
    if (diff == grand_total)
    { warningCell.className = 'calcGood';}
    else
    { 
       warningCell.className = 'calcBad';
    }
    if ((diff == 0) && (grand_total == 0))
    { warningCell.className = 'calcEmpty';}
}

function escapeStr( str) {
 if( str)
     return str.replace(/([ #;&,.+*~\':"!^$[\]()=>|\/@])/g,'\\$1')
 else
     return str;
}

$(document).ready(function(){
    $.ajaxSetup({ cache:true});

    $("a.inactive").click(function(e) {
     e.preventDefault();
     $("div.inactive").toggle();
    });


    $("select.p_customer").change(updateProjects_a);
    $("select.p_customer").updateProjects();
    $("select.c_select").change(updateProjects_a);
    $("select.c_select").updateProjects();

    //clicking the parent checkbox should check or uncheck all child checkboxes
    $(".parentCheckBox").click(
        function() {
            $(this).parents('fieldset:eq(0)').find('.childCheckBox').attr('checked', this.checked);
        }
    );
    //clicking the last unchecked or checked checkbox should check or uncheck the parent checkbox
    $('.childCheckBox').click(
        function() {
            if ($(this).parents('fieldset:eq(0)').find('.parentCheckBox').attr('checked') == true && this.checked == false)
                $(this).parents('fieldset:eq(0)').find('.parentCheckBox').attr('checked', false);
            if (this.checked == true) {
                var flag = true;
                $(this).parents('fieldset:eq(0)').find('.childCheckBox').each(
                 function() {
                     if (this.checked == false)
                         flag = false;
                 }
                );
                $(this).parents('fieldset:eq(0)').find('.parentCheckBox').attr('checked', flag);
            }
        }
    );
});

