{% extends 'label.tpl' %}

{% block content %}
<h4>
    {{ thread.subject }}
    {% if thread.labels %}
    <span class="email-labels">
    {% for label in thread.labels if not label.hidden %}
        <a href="#{{ url_for('label', label=label.id) }}">{{ label.human_name }}</a>
    {% endfor %}
    </span>
</h4>
{% endif %}
<ul class="thread">
{% for showed, emails in groups %}
    {% if not showed %}
    <div class="email-group-show"> Show {{ emails|length }} emails</div>
    {% endif %}
    <div class="email-group"{% if not showed %} style="display:none"{% endif %}>
        {{ render(emails, thread=True, show=showed) }}
    </div>
{% endfor %}
</ul>
{% endblock %}
