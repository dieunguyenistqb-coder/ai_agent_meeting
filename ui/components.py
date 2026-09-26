"""Shared presentation components; no application state or actions."""
from html import escape

import streamlit as st


def empty_state(icon, message, next_action):
    st.markdown(
        f'<div class="empty-state"><div class="empty-icon" aria-hidden="true">{escape(icon)}</div>'
        f'<strong>{escape(message)}</strong><p>{escape(next_action)}</p></div>',
        unsafe_allow_html=True,
    )


def decision_badge(decision):
    colors = {'confirmed': 'green', 'human_review': 'orange', 'not_task': 'gray',
              'rejected': 'red'}
    icons = {'confirmed': ':material/check_circle:', 'human_review': ':material/person_search:',
             'not_task': ':material/remove_circle_outline:', 'rejected': ':material/cancel:'}
    if decision:
        st.badge(str(decision), color=colors.get(decision, 'gray'), icon=icons.get(decision))
