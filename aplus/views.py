from django.shortcuts import render

# pylint: disable-next=unused-argument
def custom_404_view(request, exception=None):
    context = {
        'show_language_toggle': True,
    }
    return render(request, '404.html', context, status=404)

# pylint: disable-next=unused-argument
def custom_403_view(request, exception=None):
    context = {
        'show_language_toggle': True,
    }
    return render(request, '403.html', context, status=403)

# pylint: disable-next=unused-argument
def custom_500_view(request, exception=None):
    context = {
        'show_language_toggle': True,  
    }
    return render(request, '500.html', context, status=500)