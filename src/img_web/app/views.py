#~ Copyright (C) 2010 Nokia Corporation and/or its subsidiary(-ies).
#~ Contact: Ramez Hanna <ramez.hanna@nokia.com>
#~ This program is free software: you can redistribute it and/or modify
#~ it under the terms of the GNU General Public License as published by
#~ the Free Software Foundation, either version 3 of the License, or
#~ (at your option) any later version.

#~ This program is distributed in the hope that it will be useful,
#~ but WITHOUT ANY WARRANTY; without even the implied warranty of
#~ MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#~ GNU General Public License for more details.

#~ You should have received a copy of the GNU General Public License
#~ along with this program.  If not, see <http://www.gnu.org/licenses/>.

""" imager views """

import os, time
from urllib2 import urlopen, HTTPError
from django.http import HttpResponseRedirect, HttpResponseForbidden
from django.template import RequestContext
from django.core.urlresolvers import reverse
from django.shortcuts import render_to_response
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator, InvalidPage, EmptyPage
from django.contrib import messages

import img_web.settings as settings
from img_web.app.forms import UploadFileForm, extraReposFormset, TagForm, SearchForm
from img_web.app.models import ImageJob, Queue, GETLOG
from django.db import transaction

@login_required
@transaction.autocommit
def submit(request):    
    """
    GET: returns an unbound UploadFileForm

    POST: process a user submitted UploadFileForm
    """
    
    if request.method == 'GET':
        form = UploadFileForm(initial = {'devicegroup':settings.DEVICEGROUP,
                               'email':request.user.email}
                               )
        formset = extraReposFormset()
        return render_to_response('app/upload.html',
                                  {'form' : form, 'formset' : formset},
                                  context_instance=RequestContext(request)
                                  )

    if request.method == 'POST':
        form = UploadFileForm(request.POST, request.FILES)
        formset = extraReposFormset(request.POST)
        if not form.is_valid() or not formset.is_valid():
            return render_to_response('app/upload.html',
                                      {'form': form, 'formset' : formset},
                                       context_instance=RequestContext(request)
                                       )
        data = form.cleaned_data 
        data2 = formset.cleaned_data
        imgjob = ImageJob()

        imgjob.image_id = "%s-%s" % ( request.user.id, 
                                      time.strftime('%Y%m%d-%H%M%S') )
        imgjob.email = data['email']
        imgjob.image_type = data['imagetype']
        imgjob.user = request.user

        imgjob.overlay = data['overlay']
        imgjob.release = data['release']
        imgjob.arch = data['architecture']

        if "test_image" in data.keys():
            imgjob.devicegroup = data['devicegroup']  
            imgjob.test_image = data['test_image']

        if "notify" in data.keys():
            imgjob.notify = data["notify"]

        conf = []
        for prj in data2:
            if prj['obs']:
                repo = prj['obs'] + prj['repo'].replace(':',':/')
                conf.append(repo)

        imgjob.extra_repos = ",".join(conf)

        ksname = ""
        if 'template' in data and data['template']:
            ksname = data['template']
            filename = os.path.join(settings.TEMPLATESDIR, ksname)
            with open(filename, mode='r') as ffd:
                imgjob.kickstart = ffd.read()

        elif 'ksfile' in data and data['ksfile']:
            ksname = data['ksfile'].name
            imgjob.kickstart =  data['ksfile'].read()

        if ksname.endswith('.ks'):
            ksname = ksname[0:-3]

        imgjob.name = ksname

        imgjob.queue = Queue.objects.get(name="web")

        imgjob.save()
        
        if data["pinned"]:
            imgjob.tags.add("pinned")
        if data["tags"]:
            imgjob.tags.add(*data["tags"].split(","))
        
        return HttpResponseRedirect(reverse('img-app-queue'))


@login_required
def search(request, tag=None):
    """
    GET: returns an unbound SearchForm

    POST: process a user submitted SearchForm
    """
    
    if request.method == 'GET':
        form = SearchForm()
        alltags = [ x.name for x in ImageJob.tags.all() ]
        return render_to_response('app/search.html',
                                  {'searchform' : form,
                                   'alltags' : alltags},
                                  context_instance=RequestContext(request)
                                  )

    if request.method == 'POST':
        form = SearchForm(request.POST)
        if not form.is_valid():
            return render_to_response('app/search.html',
                                      {'searchform': form},
                                       context_instance=RequestContext(request)
                                       )
        data = form.cleaned_data
        results = ImageJob.objects.filter(tags__name__icontains = data["searchterm"])
        return render_to_response('app/search.html',
                                  {'searchform' : form,
                                   'results' : results},
                                  context_instance=RequestContext(request)
                                  )

@login_required
def queue(request, queue_name=None, dofilter=False):
    """ Shows the job queue state

    :param request: request object
    :param queu_name: Queue name to display
    :param dofilter: if True shows only current user's object
    """
    imgjobs = ImageJob.objects.all().order_by('created').reverse()
    if dofilter:
        imgjobs = imgjobs.filter(user = request.user)
    if queue_name:
        imgjobs = imgjobs.filter(queue__name = queue_name)

    paginator = Paginator(imgjobs, 30)
    try:
        page = int(request.GET.get('page', '1'))
    except ValueError:
        page = 1
    try:
        queue_page = paginator.page(page)
    except (EmptyPage, InvalidPage):
        queue_page = paginator.page(paginator.num_pages)
    return render_to_response('app/queue.html',
                              {'queue' : queue_page,
                               'queues': Queue.objects.all(),
                               'queue_name' : queue_name,
                               'filtered' : dofilter,
                               },
                              context_instance=RequestContext(request))

@login_required
def toggle_pin_job(request, msgid):
    """ Request deletion of an ImageJob

    :param msgid: ImageJob ID
    """
    imgjob = ImageJob.objects.get(image_id__exact=msgid)
    if imgjob.pinned:
        imgjob.tags.remove("pinned")
        messages.add_message(request, messages.INFO, "Image %s unpinned." % imgjob.image_id)
    else:
        imgjob.tags.add("pinned")
        messages.add_message(request, messages.INFO, "Image %s pinned." % imgjob.image_id)
        
    return HttpResponseRedirect(request.META.get('HTTP_REFERER',
                                reverse('img-app-queue')))
@login_required
def retry_job(request, msgid):
    """ Request retry of an ImageJob

    :param msgid: ImageJob ID
    """
    oldjob = ImageJob.objects.get(image_id__exact=msgid)

    imgjob = ImageJob()
    imgjob.image_id = "%s-%s" % ( request.user.id, 
                                  time.strftime('%Y%m%d-%H%M%S') )
    imgjob.user = request.user
    imgjob.email = oldjob.email
    imgjob.image_type = oldjob.image_type
    imgjob.overlay = oldjob.overlay
    imgjob.release = oldjob.release
    imgjob.arch = oldjob.arch
    imgjob.devicegroup = oldjob.devicegroup
    imgjob.test_image = oldjob.test_image
    imgjob.notify = oldjob.notify
    imgjob.extra_repos = oldjob.extra_repos
    imgjob.kickstart = oldjob.kickstart
    imgjob.name = oldjob.name
    imgjob.queue = oldjob.queue

    imgjob.save()
    messages.add_message(request, messages.INFO, "Image resubmitted with new id %s." % imgjob.image_id)
        
    return HttpResponseRedirect(reverse('img-app-queue'))
    
@login_required
def delete_job(request, msgid):
    """ Request deletion of an ImageJob

    :param msgid: ImageJob ID
    """
    imgjob = ImageJob.objects.get(image_id__exact=msgid)
    url = request.META.get('HTTP_REFERER', reverse('img-app-queue'))

    if request.user != imgjob.user and ( not request.user.is_staff \
       or not request.user.is_superuser ):
        messages.add_message(request, messages.ERROR, "Sorry, only admins are allowed to delete other people's images.")
        return HttpResponseRedirect(url)
    if imgjob.pinned:
        messages.add_message(request, messages.ERROR, "Sorry, image is pinned and cannot be deleted.")
        return HttpResponseRedirect(url)

    else:
        imgjob.delete()
        messages.add_message(request, messages.INFO, "Image %s deleted." % imgjob.image_id)
        if "queue" not in url:
            url = reverse('img-app-queue')

    return HttpResponseRedirect(url)

@login_required
def job(request, msgid):
    """ Show details about an ImageJob which are either errors or the creation
    log

    :param msgid: ImageJob ID
    """
    imgjob = ImageJob.objects.get(image_id__exact=msgid)
    error = "" 

    if request.method == 'POST':
        tagform = TagForm(request.POST)
        if not tagform.is_valid():
            return render_to_response('app/job_details.html',
                                      {'errors': {'Error' : [error]},
                                       'obj': imgjob,
                                       'tagform': tagform},
                                       context_instance=RequestContext(request))
        imgjob.tags.set(*tagform.cleaned_data['tags'])

    if imgjob.status == "IN QUEUE":
        error = "Job still in queue"
    elif imgjob.error and imgjob.error != "":
        error = imgjob.error
    else:
        # signal to launch getlog process
        GETLOG.send(sender=request, image_id = imgjob.image_id)

        return render_to_response('app/job_details.html', {'job':imgjob.log},
                                  context_instance=RequestContext(request))
    tagform = TagForm(initial = {'tags' : imgjob.tags.all()} )

    return render_to_response('app/job_details.html',
                              {'errors': {'Error' : [error]},
                               'obj': imgjob,
                               'tagform': tagform}, 
                                context_instance=RequestContext(request)) 

def index(request):
    """ Index page """
    return render_to_response('index.html',
                              context_instance=RequestContext(request))
