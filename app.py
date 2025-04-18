# Define theme colors
THEME = {
    'light': {
        'bg_primary': '#f5f5f5',
        'bg_card': '#ffffff',
        'text_primary': '#333333',
        'text_secondary': '#666666',
        'accent_primary': '#4c84ff',
        'accent_secondary': '#6bc2a1',
        'border': '#e0e0e0',
        'chart_colors': ['#4c84ff', '#6bc2a1', '#ffd166', '#ef476f', '#118ab2'],
        'chart_bg': '#ffffff',
        'chart_grid': '#e0e0e0',
        'plot_bg': '#ffffff'
    },
    'dark': {
        'bg_primary': '#1a1a1a',
        'bg_card': '#2d2d2d',
        'text_primary': '#ffffff',
        'text_secondary': '#a0aec0',
        'accent_primary': '#4c84ff',
        'accent_secondary': '#6bc2a1',
        'border': '#404040',
        'chart_colors': ['#4c84ff', '#6bc2a1', '#ffd166', '#ef476f', '#118ab2'],
        'chart_bg': '#2d2d2d',
        'chart_grid': '#404040',
        'plot_bg': '#2d2d2d'
    }
}

import streamlit as st
import requests
import re
from datetime import datetime, timedelta
import plotly.graph_objects as go
import json
import os
from dotenv import load_dotenv
from contextlib import contextmanager
from translations import TRANSLATIONS
import base64
import locale

# Load environment variables
load_dotenv()

class GitHubAPIError(Exception):
    """Custom exception for GitHub API errors."""
    def __init__(self, message, status_code=None, remaining_calls=None):
        self.message = message
        self.status_code = status_code
        self.remaining_calls = remaining_calls
        super().__init__(self.message)

def check_rate_limit():
    """Check GitHub API rate limit status."""
    try:
        response = requests.get("https://api.github.com/rate_limit")
        if response.status_code == 200:
            data = response.json()
            core = data['resources']['core']
            return {
                'remaining': core['remaining'],
                'reset_time': datetime.fromtimestamp(core['reset']).strftime('%H:%M:%S'),
                'limit': core['limit']
            }
    except Exception:
        pass
    return None

def handle_github_error(response):
    """Handle GitHub API error responses."""
    remaining_calls = response.headers.get('X-RateLimit-Remaining', 'Unknown')
    reset_time = response.headers.get('X-RateLimit-Reset')
    
    if reset_time:
        reset_time = datetime.fromtimestamp(int(reset_time)).strftime('%H:%M:%S')
    else:
        reset_time = 'Unknown'
    
    if response.status_code == 404:
        raise GitHubAPIError("Repository not found. Please check the URL.", 404, remaining_calls)
    elif response.status_code == 403:
        raise GitHubAPIError(
            f"Rate limit exceeded. Resets at {reset_time}. Remaining calls: {remaining_calls}",
            403,
            remaining_calls
        )
    elif response.status_code == 401:
        raise GitHubAPIError("Unauthorized access. Please check your credentials.", 401, remaining_calls)
    elif response.status_code == 429:
        raise GitHubAPIError(
            f"Too many requests. Please wait until {reset_time}.",
            429,
            remaining_calls
        )
    else:
        raise GitHubAPIError(
            f"GitHub API error: {response.status_code} - {response.text}",
            response.status_code,
            remaining_calls
        )

def fetch_repo_data(owner, repo):
    """Fetch repository data from GitHub API with enhanced error handling."""
    try:
        response = requests.get(
            f"https://api.github.com/repos/{owner}/{repo}",
            timeout=10  # Add timeout
        )
        
        if response.status_code != 200:
            handle_github_error(response)
        
        repo_data = response.json()
        return {
            "name": repo_data["name"],
            "description": repo_data.get("description", "No description available"),
            "stargazers_count": repo_data["stargazers_count"],
            "forks_count": repo_data["forks_count"],
            "watchers_count": repo_data["watchers_count"],
            "language": repo_data.get("language", "Not specified"),
            "created_at": format_date(repo_data["created_at"]),
            "updated_at": format_date(repo_data["updated_at"])
        }
    except requests.Timeout:
        raise GitHubAPIError("Request timed out. Please try again.")
    except requests.ConnectionError:
        raise GitHubAPIError("Connection error. Please check your internet connection.")
    except GitHubAPIError:
        raise
    except Exception as e:
        raise GitHubAPIError(f"Unexpected error: {str(e)}")

def fetch_language_stats(owner, repo):
    """Fetch language statistics with enhanced error handling."""
    try:
        response = requests.get(
            f"https://api.github.com/repos/{owner}/{repo}/languages",
            timeout=10
        )
        
        if response.status_code != 200:
            handle_github_error(response)
        
        languages = response.json()
        if not languages:
            return None
        
        total = sum(languages.values())
        return {
            lang: (count / total) * 100
            for lang, count in languages.items()
        }
    except (requests.Timeout, requests.ConnectionError, GitHubAPIError):
        raise
    except Exception as e:
        raise GitHubAPIError(f"Error fetching language statistics: {str(e)}")

def fetch_commit_activity(owner, repo):
    """Fetch weekly commit activity for the last year."""
    try:
        response = requests.get(
            f"https://api.github.com/repos/{owner}/{repo}/stats/commit_activity",
            timeout=10
        )
        
        if response.status_code == 202:
            # GitHub is computing statistics
            return {
                'status': 'computing',
                'message': 'GitHub is computing statistics. Please wait a moment and try again.'
            }
        elif response.status_code != 200:
            handle_github_error(response)
        
        data = response.json()
        if not data:
            return None
        
        # Process weekly data
        total_commits = sum(week['total'] for week in data)
        
        # Get dates for the weeks
        weeks = []
        for week in data:
            week_date = datetime.fromtimestamp(week['week']).strftime('%Y-%m-%d')
            weeks.append(week_date)
        
        # Get commits per week
        commits = [week['total'] for week in data]
        
        # Calculate daily distribution
        daily_commits = [0] * 7
        for week in data:
            for day in range(7):
                daily_commits[day] += week['days'][day]
        
        return {
            'status': 'ready',
            'total_commits': total_commits,
            'weeks': weeks,
            'commits': commits,
            'daily_commits': daily_commits
        }
    
    except requests.Timeout:
        raise GitHubAPIError("Request timed out while fetching commit activity.")
    except requests.ConnectionError:
        raise GitHubAPIError("Connection error while fetching commit activity.")
    except Exception as e:
        raise GitHubAPIError(f"Error fetching commit activity: {str(e)}")

def plot_language_stats(language_stats):
    """Create an enhanced language statistics visualization."""
    theme = THEME[st.session_state.theme]
    
    # Sort languages by percentage
    sorted_langs = dict(sorted(language_stats.items(), key=lambda x: x[1], reverse=True))
    
    fig = go.Figure()
    
    # Add pie chart
    fig.add_trace(go.Pie(
        labels=list(sorted_langs.keys()),
        values=list(sorted_langs.values()),
        hole=0.4,
        marker=dict(
            colors=theme['chart_colors'][:len(sorted_langs)],
            line=dict(color=theme['border'], width=1)
        ),
        textinfo='label+percent',
        textposition='outside',
        hovertemplate="<b>%{label}</b><br>" +
                     "Percentage: %{percent}<br>" +
                     "<extra></extra>"
    ))
    
    # Update layout
    fig.update_layout(
        title=dict(
            text="Language Distribution",
            font=dict(size=16, color=theme['text_primary'])
        ),
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=-0.5,
            xanchor="center",
            x=0.5,
            font=dict(color=theme['text_primary']),
            bgcolor=theme['plot_bg'],
            bordercolor=theme['border']
        ),
        plot_bgcolor=theme['plot_bg'],
        paper_bgcolor=theme['plot_bg'],
        margin=dict(t=50, b=100, l=20, r=20),
        height=500,  # Increased height
        width=None,  # Let it be responsive
        annotations=[
            dict(
                text="Language<br>Distribution",
                x=0.5,
                y=0.5,
                font=dict(size=14, color=theme['text_primary']),
                showarrow=False
            )
        ]
    )
    
    return fig

def plot_commit_activity(commit_data):
    """Create an enhanced commit activity visualization."""
    if commit_data.get('status') == 'computing':
        st.info("⏳ " + commit_data['message'])
        return None
    
    theme = THEME[st.session_state.theme]
    
    fig = go.Figure()
    
    # Add weekly commit bars
    fig.add_trace(go.Bar(
        x=commit_data["weeks"],
        y=commit_data["commits"],
        name="Weekly Commits",
        marker=dict(
            color=theme['accent_primary'],
            opacity=0.8
        ),
        hovertemplate="Week of %{x}<br>Commits: %{y}<extra></extra>"
    ))
    
    # Update layout
    fig.update_layout(
        title=dict(
            text=f"Commit Activity (Past Year) - Total: {commit_data['total_commits']:,} commits",
            font=dict(size=16, color=theme['text_primary'])
        ),
        showlegend=False,
        xaxis_title="Week",
        yaxis_title="Number of Commits",
        plot_bgcolor=theme['plot_bg'],
        paper_bgcolor=theme['plot_bg'],
        font=dict(color=theme['text_primary']),
        xaxis=dict(
            gridcolor=theme['chart_grid'],
            tickangle=45,
            tickformat="%b %Y",
            nticks=12,
            showgrid=True,
            tickfont=dict(color=theme['text_primary'])
        ),
        yaxis=dict(
            gridcolor=theme['chart_grid'],
            zerolinecolor=theme['chart_grid'],
            showgrid=True,
            tickfont=dict(color=theme['text_primary'])
        ),
        margin=dict(t=50, b=50, l=50, r=50),
        height=400
    )
    
    return fig

def plot_daily_distribution(commit_data):
    """Create a daily distribution visualization."""
    if commit_data.get('status') == 'computing':
        st.info("⏳ " + commit_data['message'])
        return None
    
    theme = THEME[st.session_state.theme]
    
    days = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
    daily_commits = commit_data["daily_commits"]
    
    fig = go.Figure()
    
    # Add daily commit bars
    fig.add_trace(go.Bar(
        x=days,
        y=daily_commits,
        marker=dict(
            color=theme['accent_primary'],
            opacity=0.8
        ),
        hovertemplate="%{x}<br>Total Commits: %{y}<extra></extra>"
    ))
    
    # Update layout
    fig.update_layout(
        title=dict(
            text="Commit Distribution by Day of Week",
            font=dict(size=16, color=theme['text_primary'])
        ),
        showlegend=False,
        xaxis_title="Day of Week",
        yaxis_title="Total Commits",
        plot_bgcolor=theme['plot_bg'],
        paper_bgcolor=theme['plot_bg'],
        font=dict(color=theme['text_primary']),
        xaxis=dict(
            gridcolor=theme['chart_grid'],
            showgrid=True,
            tickfont=dict(color=theme['text_primary'])
        ),
        yaxis=dict(
            gridcolor=theme['chart_grid'],
            zerolinecolor=theme['chart_grid'],
            showgrid=True,
            tickfont=dict(color=theme['text_primary'])
        ),
        height=300,
        margin=dict(t=50, b=50, l=50, r=50)
    )
    
    return fig

def display_repo_overview(repo_info):
    """Display repository overview with tooltips and heatmaps."""
    st.header(repo_info["name"])
    st.markdown(repo_info["description"] or "No description provided")
    
    # Create metrics with tooltips
    metrics_html = f"""
    <div class="metrics-container">
        {create_tooltip(
            f'<div class="metric-container"><div class="metric-value">{format_number(repo_info["stargazers_count"])}</div><div class="metric-label">Stars</div></div>',
            "Number of users who have starred this repository, indicating its popularity"
        )}
        {create_tooltip(
            f'<div class="metric-container"><div class="metric-value">{format_number(repo_info["forks_count"])}</div><div class="metric-label">Forks</div></div>',
            "Number of repository copies made by other users for their own development"
        )}
        {create_tooltip(
            f'<div class="metric-container"><div class="metric-value">{format_number(repo_info["watchers_count"])}</div><div class="metric-label">Watchers</div></div>',
            "Users following this repository to receive notifications about activity"
        )}
        {create_tooltip(
            f'<div class="metric-container"><div class="metric-value">{repo_info["language"] or "N/A"}</div><div class="metric-label">Primary Language</div></div>',
            "The most commonly used programming language in this repository"
        )}
    </div>
    """
    st.markdown(metrics_html, unsafe_allow_html=True)

def display_language_details(language_stats):
    """Display detailed language statistics with tooltips and heatmaps."""
    st.subheader("Language Breakdown")
    
    # Find maximum bytes for heatmap scaling
    max_bytes = max(stats['bytes'] for stats in language_stats.values())
    
    # Create language details with heatmap and tooltips
    for lang, stats in sorted(language_stats.items(), key=lambda x: x[1]['bytes'], reverse=True):
        heatmap_class = get_heatmap_class(stats['bytes'], max_bytes)
        
        lang_html = f"""
        <div style="margin: 8px 0;">
            {create_tooltip(
                f'<span class="heatmap {heatmap_class}">{lang}: {stats["percentage"]}%</span>',
                f"Total size: {format_number(stats['bytes'])} bytes<br>"
                f"Common file types: {get_language_file_types(lang)}<br>"
                f"Typical use: {get_language_description(lang)}"
            )}
        </div>
        """
        st.markdown(lang_html, unsafe_allow_html=True)

def get_language_file_types(language):
    """Get common file types for a programming language."""
    language_files = {
        "Python": ".py, .pyw, .pyx",
        "JavaScript": ".js, .jsx, .mjs",
        "TypeScript": ".ts, .tsx",
        "Java": ".java, .class, .jar",
        "C++": ".cpp, .hpp, .cc",
        "HTML": ".html, .htm",
        "CSS": ".css, .scss, .sass",
        "Ruby": ".rb, .erb",
        "Go": ".go",
        "Rust": ".rs",
    }
    return language_files.get(language, "Various files")

def get_language_description(language):
    """Get a brief description of a programming language."""
    descriptions = {
        "Python": "General-purpose language known for readability and extensive libraries",
        "JavaScript": "Web programming language for client-side and server-side development",
        "TypeScript": "Typed superset of JavaScript for large-scale applications",
        "Java": "Object-oriented language for enterprise and Android development",
        "C++": "Systems programming language for performance-critical applications",
        "HTML": "Markup language for structuring web content",
        "CSS": "Style sheet language for web page presentation",
        "Ruby": "Dynamic language focused on simplicity and productivity",
        "Go": "Concurrent programming language for scalable network services",
        "Rust": "Systems language focusing on safety and performance",
    }
    return descriptions.get(language, "Programming language")

def create_help_section():
    """Create a help section with FAQ and tooltips."""
    with st.expander("❓ Help & FAQ", expanded=False):
        st.markdown("""
        ### How to Use This App
        1. **Enter Repository URL**: Paste any public GitHub repository URL in the input field
        2. **Analyze**: Click the 'Analyze Repository' button to start the analysis
        3. **View Results**: Explore various metrics and visualizations about the repository
        
        ### Features
        - **Repository Overview**: Basic information like stars, forks, and watchers
        - **Language Statistics**: Breakdown of programming languages used
        - **Commit Activity**: Visualization of commit patterns over time
        - **Daily Distribution**: Analysis of commit patterns by day of week
        
        ### FAQ
        **Q: What types of repositories can I analyze?**
        - Any public GitHub repository
        
        **Q: Why can't I see data for some repositories?**
        - The repository might be private
        - GitHub API rate limits might have been reached
        - The repository might be empty or new
        
        **Q: What do the visualizations show?**
        - **Language Chart**: Distribution of programming languages by code size
        - **Commit Activity**: Weekly commit patterns over the past year
        - **Daily Distribution**: Which days of the week have the most activity
        
        **Q: How often is the data updated?**
        - Data is fetched in real-time when you analyze a repository
        """)

def add_tooltips():
    """Add tooltips to various UI elements."""
    tooltips = {
        'repo_url': 'Enter the URL of any public GitHub repository (e.g., https://github.com/username/repo)',
        'analyze_button': 'Click to start analyzing the repository',
        'theme_toggle': 'Switch between light and dark mode',
        'stars': 'Number of users who have starred this repository',
        'forks': 'Number of times this repository has been forked',
        'watchers': 'Number of users watching this repository',
        'languages': 'Distribution of programming languages used in the repository',
        'commit_activity': 'Pattern of commits over the past year',
        'daily_distribution': 'Distribution of commits across days of the week'
    }
    return tooltips

def format_number(number):
    """Format large numbers with K/M/B suffixes."""
    if number >= 1_000_000_000:
        return f"{number/1_000_000_000:.1f}B"
    if number >= 1_000_000:
        return f"{number/1_000_000:.1f}M"
    if number >= 1_000:
        return f"{number/1_000:.1f}K"
    return str(number)

def create_metric(label, value):
    """Create a metric component with custom styling."""
    return f"""
        <div class="metric-container">
            <div class="metric-value">{value}</div>
            <div class="metric-label">{label}</div>
        </div>
    """

def extract_repo_info(url):
    """Extract owner and repo name from GitHub URL."""
    pattern = r"github\.com/([^/]+)/([^/]+)"
    match = re.search(pattern, url)
    if match:
        owner, repo = match.group(1), match.group(2)
        # Remove .git suffix if present
        repo = repo.replace(".git", "")
        return owner, repo
    return None, None

def fetch_repo_data(owner, repo):
    """Fetch repository data from GitHub API with enhanced error handling."""
    try:
        response = requests.get(
            f"https://api.github.com/repos/{owner}/{repo}",
            timeout=10  # Add timeout
        )
        
        if response.status_code != 200:
            handle_github_error(response)
        
        repo_data = response.json()
        return {
            "name": repo_data["name"],
            "description": repo_data.get("description", "No description available"),
            "stargazers_count": repo_data["stargazers_count"],
            "forks_count": repo_data["forks_count"],
            "watchers_count": repo_data["watchers_count"],
            "language": repo_data.get("language", "Not specified"),
            "created_at": format_date(repo_data["created_at"]),
            "updated_at": format_date(repo_data["updated_at"])
        }
    except requests.Timeout:
        raise GitHubAPIError("Request timed out. Please try again.")
    except requests.ConnectionError:
        raise GitHubAPIError("Connection error. Please check your internet connection.")
    except GitHubAPIError:
        raise
    except Exception as e:
        raise GitHubAPIError(f"Unexpected error: {str(e)}")

def fetch_language_stats(owner, repo):
    """Fetch language statistics with enhanced error handling."""
    try:
        response = requests.get(
            f"https://api.github.com/repos/{owner}/{repo}/languages",
            timeout=10
        )
        
        if response.status_code != 200:
            handle_github_error(response)
        
        languages = response.json()
        if not languages:
            return None
        
        total = sum(languages.values())
        return {
            lang: (count / total) * 100
            for lang, count in languages.items()
        }
    except (requests.Timeout, requests.ConnectionError, GitHubAPIError):
        raise
    except Exception as e:
        raise GitHubAPIError(f"Error fetching language statistics: {str(e)}")

def fetch_commit_activity(owner, repo):
    """Fetch weekly commit activity for the last year."""
    try:
        response = requests.get(
            f"https://api.github.com/repos/{owner}/{repo}/stats/commit_activity",
            timeout=10
        )
        
        if response.status_code == 202:
            # GitHub is computing statistics
            return {
                'status': 'computing',
                'message': 'GitHub is computing statistics. Please wait a moment and try again.'
            }
        elif response.status_code != 200:
            handle_github_error(response)
        
        data = response.json()
        if not data:
            return None
        
        # Process weekly data
        total_commits = sum(week['total'] for week in data)
        
        # Get dates for the weeks
        weeks = []
        for week in data:
            week_date = datetime.fromtimestamp(week['week']).strftime('%Y-%m-%d')
            weeks.append(week_date)
        
        # Get commits per week
        commits = [week['total'] for week in data]
        
        # Calculate daily distribution
        daily_commits = [0] * 7
        for week in data:
            for day in range(7):
                daily_commits[day] += week['days'][day]
        
        return {
            'status': 'ready',
            'total_commits': total_commits,
            'weeks': weeks,
            'commits': commits,
            'daily_commits': daily_commits
        }
    
    except requests.Timeout:
        raise GitHubAPIError("Request timed out while fetching commit activity.")
    except requests.ConnectionError:
        raise GitHubAPIError("Connection error while fetching commit activity.")
    except Exception as e:
        raise GitHubAPIError(f"Error fetching commit activity: {str(e)}")

def plot_language_stats(language_stats):
    """Create an enhanced language statistics visualization."""
    theme = THEME[st.session_state.theme]
    
    # Sort languages by percentage
    sorted_langs = dict(sorted(language_stats.items(), key=lambda x: x[1], reverse=True))
    
    fig = go.Figure()
    
    # Add pie chart
    fig.add_trace(go.Pie(
        labels=list(sorted_langs.keys()),
        values=list(sorted_langs.values()),
        hole=0.4,
        marker=dict(
            colors=theme['chart_colors'][:len(sorted_langs)],
            line=dict(color=theme['border'], width=1)
        ),
        textinfo='label+percent',
        textposition='outside',
        hovertemplate="<b>%{label}</b><br>" +
                     "Percentage: %{percent}<br>" +
                     "<extra></extra>"
    ))
    
    # Update layout
    fig.update_layout(
        title=dict(
            text="Language Distribution",
            font=dict(size=16, color=theme['text_primary'])
        ),
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=-0.5,
            xanchor="center",
            x=0.5,
            font=dict(color=theme['text_primary']),
            bgcolor=theme['plot_bg'],
            bordercolor=theme['border']
        ),
        plot_bgcolor=theme['plot_bg'],
        paper_bgcolor=theme['plot_bg'],
        margin=dict(t=50, b=100, l=20, r=20),
        height=500,  # Increased height
        width=None,  # Let it be responsive
        annotations=[
            dict(
                text="Language<br>Distribution",
                x=0.5,
                y=0.5,
                font=dict(size=14, color=theme['text_primary']),
                showarrow=False
            )
        ]
    )
    
    return fig

def plot_commit_activity(commit_data):
    """Create an enhanced commit activity visualization."""
    if commit_data.get('status') == 'computing':
        st.info("⏳ " + commit_data['message'])
        return None
    
    theme = THEME[st.session_state.theme]
    
    fig = go.Figure()
    
    # Add weekly commit bars
    fig.add_trace(go.Bar(
        x=commit_data["weeks"],
        y=commit_data["commits"],
        name="Weekly Commits",
        marker=dict(
            color=theme['accent_primary'],
            opacity=0.8
        ),
        hovertemplate="Week of %{x}<br>Commits: %{y}<extra></extra>"
    ))
    
    # Update layout
    fig.update_layout(
        title=dict(
            text=f"Commit Activity (Past Year) - Total: {commit_data['total_commits']:,} commits",
            font=dict(size=16, color=theme['text_primary'])
        ),
        showlegend=False,
        xaxis_title="Week",
        yaxis_title="Number of Commits",
        plot_bgcolor=theme['plot_bg'],
        paper_bgcolor=theme['plot_bg'],
        font=dict(color=theme['text_primary']),
        xaxis=dict(
            gridcolor=theme['chart_grid'],
            tickangle=45,
            tickformat="%b %Y",
            nticks=12,
            showgrid=True,
            tickfont=dict(color=theme['text_primary'])
        ),
        yaxis=dict(
            gridcolor=theme['chart_grid'],
            zerolinecolor=theme['chart_grid'],
            showgrid=True,
            tickfont=dict(color=theme['text_primary'])
        ),
        margin=dict(t=50, b=50, l=50, r=50),
        height=400
    )
    
    return fig

def plot_daily_distribution(commit_data):
    """Create a daily distribution visualization."""
    if commit_data.get('status') == 'computing':
        st.info("⏳ " + commit_data['message'])
        return None
    
    theme = THEME[st.session_state.theme]
    
    days = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
    daily_commits = commit_data["daily_commits"]
    
    fig = go.Figure()
    
    # Add daily commit bars
    fig.add_trace(go.Bar(
        x=days,
        y=daily_commits,
        marker=dict(
            color=theme['accent_primary'],
            opacity=0.8
        ),
        hovertemplate="%{x}<br>Total Commits: %{y}<extra></extra>"
    ))
    
    # Update layout
    fig.update_layout(
        title=dict(
            text="Commit Distribution by Day of Week",
            font=dict(size=16, color=theme['text_primary'])
        ),
        showlegend=False,
        xaxis_title="Day of Week",
        yaxis_title="Total Commits",
        plot_bgcolor=theme['plot_bg'],
        paper_bgcolor=theme['plot_bg'],
        font=dict(color=theme['text_primary']),
        xaxis=dict(
            gridcolor=theme['chart_grid'],
            showgrid=True,
            tickfont=dict(color=theme['text_primary'])
        ),
        yaxis=dict(
            gridcolor=theme['chart_grid'],
            zerolinecolor=theme['chart_grid'],
            showgrid=True,
            tickfont=dict(color=theme['text_primary'])
        ),
        height=300,
        margin=dict(t=50, b=50, l=50, r=50)
    )
    
    return fig

def display_repo_overview(repo_info):
    """Display repository overview with tooltips and heatmaps."""
    st.header(repo_info["name"])
    st.markdown(repo_info["description"] or "No description provided")
    
    # Create metrics with tooltips
    metrics_html = f"""
    <div class="metrics-container">
        {create_tooltip(
            f'<div class="metric-container"><div class="metric-value">{format_number(repo_info["stargazers_count"])}</div><div class="metric-label">Stars</div></div>',
            "Number of users who have starred this repository, indicating its popularity"
        )}
        {create_tooltip(
            f'<div class="metric-container"><div class="metric-value">{format_number(repo_info["forks_count"])}</div><div class="metric-label">Forks</div></div>',
            "Number of repository copies made by other users for their own development"
        )}
        {create_tooltip(
            f'<div class="metric-container"><div class="metric-value">{format_number(repo_info["watchers_count"])}</div><div class="metric-label">Watchers</div></div>',
            "Users following this repository to receive notifications about activity"
        )}
        {create_tooltip(
            f'<div class="metric-container"><div class="metric-value">{repo_info["language"] or "N/A"}</div><div class="metric-label">Primary Language</div></div>',
            "The most commonly used programming language in this repository"
        )}
    </div>
    """
    st.markdown(metrics_html, unsafe_allow_html=True)

def display_language_details(language_stats):
    """Display detailed language statistics with tooltips and heatmaps."""
    st.subheader("Language Breakdown")
    
    # Find maximum bytes for heatmap scaling
    max_bytes = max(stats['bytes'] for stats in language_stats.values())
    
    # Create language details with heatmap and tooltips
    for lang, stats in sorted(language_stats.items(), key=lambda x: x[1]['bytes'], reverse=True):
        heatmap_class = get_heatmap_class(stats['bytes'], max_bytes)
        
        lang_html = f"""
        <div style="margin: 8px 0;">
            {create_tooltip(
                f'<span class="heatmap {heatmap_class}">{lang}: {stats["percentage"]}%</span>',
                f"Total size: {format_number(stats['bytes'])} bytes<br>"
                f"Common file types: {get_language_file_types(lang)}<br>"
                f"Typical use: {get_language_description(lang)}"
            )}
        </div>
        """
        st.markdown(lang_html, unsafe_allow_html=True)

def get_language_file_types(language):
    """Get common file types for a programming language."""
    language_files = {
        "Python": ".py, .pyw, .pyx",
        "JavaScript": ".js, .jsx, .mjs",
        "TypeScript": ".ts, .tsx",
        "Java": ".java, .class, .jar",
        "C++": ".cpp, .hpp, .cc",
        "HTML": ".html, .htm",
        "CSS": ".css, .scss, .sass",
        "Ruby": ".rb, .erb",
        "Go": ".go",
        "Rust": ".rs",
    }
    return language_files.get(language, "Various files")

def get_language_description(language):
    """Get a brief description of a programming language."""
    descriptions = {
        "Python": "General-purpose language known for readability and extensive libraries",
        "JavaScript": "Web programming language for client-side and server-side development",
        "TypeScript": "Typed superset of JavaScript for large-scale applications",
        "Java": "Object-oriented language for enterprise and Android development",
        "C++": "Systems programming language for performance-critical applications",
        "HTML": "Markup language for structuring web content",
        "CSS": "Style sheet language for web page presentation",
        "Ruby": "Dynamic language focused on simplicity and productivity",
        "Go": "Concurrent programming language for scalable network services",
        "Rust": "Systems language focusing on safety and performance",
    }
    return descriptions.get(language, "Programming language")

def create_help_section():
    """Create a help section with FAQ and tooltips."""
    with st.expander("❓ Help & FAQ", expanded=False):
        st.markdown("""
        ### How to Use This App
        1. **Enter Repository URL**: Paste any public GitHub repository URL in the input field
        2. **Analyze**: Click the 'Analyze Repository' button to start the analysis
        3. **View Results**: Explore various metrics and visualizations about the repository
        
        ### Features
        - **Repository Overview**: Basic information like stars, forks, and watchers
        - **Language Statistics**: Breakdown of programming languages used
        - **Commit Activity**: Visualization of commit patterns over time
        - **Daily Distribution**: Analysis of commit patterns by day of week
        
        ### FAQ
        **Q: What types of repositories can I analyze?**
        - Any public GitHub repository
        
        **Q: Why can't I see data for some repositories?**
        - The repository might be private
        - GitHub API rate limits might have been reached
        - The repository might be empty or new
        
        **Q: What do the visualizations show?**
        - **Language Chart**: Distribution of programming languages by code size
        - **Commit Activity**: Weekly commit patterns over the past year
        - **Daily Distribution**: Which days of the week have the most activity
        
        **Q: How often is the data updated?**
        - Data is fetched in real-time when you analyze a repository
        """)

def add_tooltips():
    """Add tooltips to various UI elements."""
    tooltips = {
        'repo_url': 'Enter the URL of any public GitHub repository (e.g., https://github.com/username/repo)',
        'analyze_button': 'Click to start analyzing the repository',
        'theme_toggle': 'Switch between light and dark mode',
        'stars': 'Number of users who have starred this repository',
        'forks': 'Number of times this repository has been forked',
        'watchers': 'Number of users watching this repository',
        'languages': 'Distribution of programming languages used in the repository',
        'commit_activity': 'Pattern of commits over the past year',
        'daily_distribution': 'Distribution of commits across days of the week'
    }
    return tooltips

def format_date(date_str):
    """Format date string from GitHub API."""
    return datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%SZ").strftime("%Y-%m-%d")

def initialize_session_state():
    """Initialize session state variables."""
    if 'theme' not in st.session_state:
        st.session_state.theme = 'light'
    
    if 'language' not in st.session_state:
        try:
            system_lang = locale.getdefaultlocale()[0][:2]
            st.session_state.language = system_lang if system_lang in TRANSLATIONS else 'en'
        except:
            st.session_state.language = 'en'

def get_text(key):
    """Get translated text for the given key."""
    return TRANSLATIONS[st.session_state.language][key]

def create_drag_drop_area():
    """Create a drag and drop area for file upload."""
    st.markdown("""
        <style>
            .upload-area {
                width: 100%;
                height: 150px;
                border: 2px dashed #ccc;
                border-radius: 5px;
                text-align: center;
                padding: 20px;
                margin: 20px 0;
                cursor: pointer;
            }
            .upload-area:hover {
                border-color: #666;
            }
            .upload-text {
                color: #666;
                margin-top: 10px;
            }
        </style>
    """, unsafe_allow_html=True)
    
    uploaded_file = st.file_uploader(
        get_text('upload_text'),
        type=['txt', 'json', 'yml', 'yaml'],
        key="repo_file_uploader"
    )
    
    return uploaded_file

def process_uploaded_file(uploaded_file):
    """Process the uploaded configuration file."""
    if uploaded_file is not None:
        try:
            content = uploaded_file.read().decode()
            if uploaded_file.name.endswith('.json'):
                return json.loads(content)
            elif uploaded_file.name.endswith(('.yml', '.yaml')):
                import yaml
                return yaml.safe_load(content)
            else:
                # Assume it's a text file with repository URLs
                return {'repositories': [line.strip() for line in content.splitlines() if line.strip()]}
        except Exception as e:
            st.error(f"Error processing file: {str(e)}")
    return None

def display_rate_limit_info():
    """Display GitHub API rate limit information."""
    rate_info = check_rate_limit()
    if rate_info:
        with st.sidebar:
            st.write("### GitHub API Status")
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Remaining Calls", rate_info['remaining'])
            with col2:
                st.metric("Resets At", rate_info['reset_time'])

def display_error_message(error):
    """Display a formatted error message with appropriate styling."""
    if isinstance(error, GitHubAPIError):
        if error.status_code in [403, 429]:
            st.error(f"🚫 {error.message}")
            st.warning(
                "To avoid rate limiting, consider:\n"
                "1. Waiting until the rate limit resets\n"
                "2. Using a GitHub personal access token\n"
                "3. Checking the API status in the sidebar"
            )
        elif error.status_code == 404:
            st.error("🔍 " + error.message)
            st.info(
                "Please ensure:\n"
                "1. The repository URL is correct\n"
                "2. The repository exists and is public\n"
                "3. You have typed the owner and repository name correctly"
            )
        elif error.status_code == 401:
            st.error("🔒 " + error.message)
            st.info(
                "If you're trying to access a private repository:\n"
                "1. Make sure you have the correct permissions\n"
                "2. Use a GitHub personal access token with appropriate scopes"
            )
        else:
            st.error(f"❌ {error.message}")
    else:
        st.error(f"❌ An unexpected error occurred: {str(error)}")

def inject_custom_css():
    """Inject custom CSS for dashboard styling."""
    theme = THEME[st.session_state.theme]
    st.markdown(
        f"""
        <style>
            /* Main container */
            .stApp {{
                background-color: {theme['bg_primary']};
                color: {theme['text_primary']};
            }}
            
            /* Dashboard cards */
            .dashboard-card {{
                background-color: {theme['bg_card']};
                border: 1px solid {theme['border']};
                border-radius: 12px;
                padding: 1.5rem;
                margin-bottom: 1rem;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }}
            
            /* Metrics container */
            .metrics-container {{
                display: flex;
                flex-wrap: wrap;
                gap: 1rem;
                margin: 1rem 0;
            }}
            
            .metric-container {{
                flex: 1;
                min-width: 120px;
                padding: 1rem;
                background-color: {theme['bg_card']};
                border: 1px solid {theme['border']};
                border-radius: 8px;
                text-align: center;
            }}
            
            .metric-value {{
                font-size: 1.5rem;
                font-weight: bold;
                color: {theme['text_primary']};
                margin-bottom: 0.5rem;
            }}
            
            .metric-label {{
                color: {theme['text_secondary']};
                font-size: 0.9rem;
            }}
            
            /* Theme toggle button */
            .stButton button {{
                width: 100%;
                border-color: {theme['border']} !important;
                color: {theme['text_primary']} !important;
                background-color: {theme['bg_card']} !important;
            }}
            
            .stButton button:hover {{
                border-color: {theme['accent_primary']} !important;
                color: {theme['accent_primary']} !important;
            }}
            
            /* Headers */
            h1, h2, h3, h4, h5, h6 {{
                color: {theme['text_primary']} !important;
                font-weight: 600 !important;
            }}
            
            /* Text elements */
            p, span, div {{
                color: {theme['text_primary']};
            }}
            
            /* Input fields */
            .stTextInput input {{
                background-color: {theme['bg_card']};
                color: {theme['text_primary']};
                border: 1px solid {theme['border']};
                border-radius: 6px;
                padding: 0.5rem 1rem;
            }}
            .stTextInput input:focus {{
                border-color: {theme['accent_primary']};
                box-shadow: 0 0 0 2px {theme['accent_primary']}33;
            }}
            
            /* Expander styling */
            .streamlit-expanderHeader {{
                background-color: {theme['bg_card']};
                color: {theme['text_primary']};
                border-radius: 6px;
                border: 1px solid {theme['border']};
            }}
            
            /* File uploader */
            .stFileUploader {{
                background-color: {theme['bg_card']};
                border: 2px dashed {theme['border']};
                border-radius: 8px;
                padding: 1rem;
                text-align: center;
                transition: all 0.3s ease;
            }}
            
            .stFileUploader:hover {{
                border-color: {theme['accent_primary']};
            }}
            
            /* Radio buttons */
            .stRadio > label {{
                color: {theme['text_primary']} !important;
            }}
            
            /* Tooltips */
            .tooltip {{
                position: relative;
                display: inline-block;
                border-bottom: 1px dotted {theme['text_secondary']};
            }}
            
            .tooltip .tooltip-text {{
                visibility: hidden;
                background-color: {theme['bg_card']};
                color: {theme['text_primary']};
                text-align: center;
                padding: 5px;
                border-radius: 6px;
                border: 1px solid {theme['border']};
                
                /* Position the tooltip */
                position: absolute;
                z-index: 1;
                bottom: 125%;
                left: 50%;
                margin-left: -60px;
                
                /* Fade in tooltip */
                opacity: 0;
                transition: opacity 0.3s;
            }}
            
            .tooltip:hover .tooltip-text {{
                visibility: visible;
                opacity: 1;
            }}
            
            /* Loading animations */
            @keyframes shimmer {{
                0% {{ background-position: -1000px 0; }}
                100% {{ background-position: 1000px 0; }}
            }}
            
            .skeleton {{
                background: linear-gradient(90deg, 
                    {theme['bg_card']} 0px, 
                    {theme['border']} 40px, 
                    {theme['bg_card']} 80px);
                background-size: 1000px 100%;
                animation: shimmer 2s infinite linear;
                border-radius: 4px;
                margin: 8px 0;
                min-height: 80px;
            }}
            
            /* Retry button styling */
            .retry-button {{
                background-color: {theme['accent_primary']};
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                cursor: pointer;
                transition: all 0.3s ease;
            }}
            
            .retry-button:hover {{
                background-color: {theme['accent_secondary']};
                transform: translateY(-1px);
            }}
        </style>
        """,
        unsafe_allow_html=True
    )

def main():
    # Initialize session state first
    initialize_session_state()
    
    # Now we can safely use session state variables
    st.set_page_config(page_title=get_text('title'), page_icon="📊", layout="wide")
    
    # Display rate limit information
    display_rate_limit_info()
    
    # Header with language selector and theme toggle
    header_col1, header_col2, header_col3 = st.columns([5, 1, 1])
    
    with header_col1:
        st.title(get_text('title'))
        st.markdown(get_text('description'))
    
    with header_col2:
        # Language selector
        selected_lang = st.selectbox(
            '',
            options=['en', 'es', 'fr'],
            format_func=lambda x: {'en': 'English', 'es': 'Español', 'fr': 'Français'}[x],
            index=['en', 'es', 'fr'].index(st.session_state.language)
        )
        if selected_lang != st.session_state.language:
            st.session_state.language = selected_lang
            st.experimental_rerun()
    
    with header_col3:
        # Theme toggle
        theme_button = st.button('🌓', help=get_text('theme_tooltip'))
        if theme_button:
            current_theme = st.session_state.theme
            st.session_state.theme = 'dark' if current_theme == 'light' else 'light'
    
    # Apply theme-specific CSS
    inject_custom_css()
    
    # Repository input methods
    input_method = st.radio(
        "",
        options=["URL", "File Upload"],
        horizontal=True,
        label_visibility="collapsed"
    )
    
    repo_urls = []
    
    if input_method == "URL":
        # URL input
        repo_url = st.text_input(
            get_text('enter_url'),
            help=get_text('url_tooltip')
        )
        if repo_url:
            repo_urls = [repo_url]
    else:
        # File upload with drag and drop
        uploaded_file = create_drag_drop_area()
        if uploaded_file:
            try:
                config = process_uploaded_file(uploaded_file)
                if config and 'repositories' in config:
                    repo_urls = config['repositories']
            except Exception as e:
                st.error(f"Error processing uploaded file: {str(e)}")
    
    if st.button(get_text('analyze_button'), help=get_text('analyze_tooltip')):
        if not repo_urls:
            st.error(get_text('error_no_url'))
            return
        
        # Create a container for the analysis results
        results_container = st.container()
        
        for repo_url in repo_urls:
            try:
                # Extract owner and repo name
                owner, repo = extract_repo_info(repo_url)
                if not owner or not repo:
                    st.error(f"Invalid repository URL format: {repo_url}")
                    continue
                
                with st.spinner(get_text('loading')):
                    # Fetch repository information
                    repo_info = fetch_repo_data(owner, repo)
                    
                    # Create expandable section for each repository
                    with results_container.expander(f"📂 {owner}/{repo}", expanded=True):
                        # Display repository information
                        st.header(get_text('repo_overview'))
                        
                        # Create metrics with tooltips
                        col1, col2, col3 = st.columns(3)
                        with col1:
                            st.metric('⭐ ' + get_text('stars'),
                                    repo_info['stargazers_count'])
                        with col2:
                            st.metric('🔄 ' + get_text('forks'),
                                    repo_info['forks_count'])
                        with col3:
                            st.metric('👀 ' + get_text('watchers'),
                                    repo_info['watchers_count'])
                        
                        # Repository details
                        st.subheader(get_text('repo_details'))
                        details_col1, details_col2 = st.columns(2)
                        with details_col1:
                            st.write(f"**{get_text('description_label')}:** {repo_info['description']}")
                            st.write(f"**{get_text('language_label')}:** {repo_info['language']}")
                        with details_col2:
                            st.write(f"**{get_text('created_label')}:** {repo_info['created_at']}")
                            st.write(f"**{get_text('updated_label')}:** {repo_info['updated_at']}")
                        
                        try:
                            # Language statistics
                            st.subheader(get_text('lang_stats'))
                            language_stats = fetch_language_stats(owner, repo)
                            if language_stats:
                                fig = plot_language_stats(language_stats)
                                st.plotly_chart(fig, use_container_width=True)
                            else:
                                st.info("No language statistics available for this repository.")
                        except Exception as e:
                            st.warning(f"Could not load language statistics: {str(e)}")
                        
                        # Initialize commit_data at a higher scope
                        commit_data = None
                        
                        try:
                            # Commit activity
                            st.subheader(get_text('commit_activity'))
                            commit_data = fetch_commit_activity(owner, repo)
                            if commit_data:
                                if commit_data.get('status') == 'computing':
                                    st.info("⏳ " + commit_data['message'])
                                    # Add a retry button
                                    if st.button("Retry Loading Commit Data", key=f"retry_{owner}_{repo}"):
                                        st.experimental_rerun()
                                else:
                                    fig = plot_commit_activity(commit_data)
                                    if fig:
                                        st.plotly_chart(fig, use_container_width=True)
                            else:
                                st.info("No commit activity data available for this repository.")
                        except Exception as e:
                            st.warning(f"Could not load commit activity: {str(e)}")
                        
                        try:
                            # Daily distribution
                            if commit_data and commit_data.get('status') == 'ready':
                                st.subheader(get_text('daily_dist'))
                                fig = plot_daily_distribution(commit_data)
                                if fig:
                                    st.plotly_chart(fig, use_container_width=True)
                        except Exception as e:
                            st.warning(f"Could not load daily distribution: {str(e)}")
            
            except GitHubAPIError as e:
                display_error_message(e)
            except Exception as e:
                st.error(f"An unexpected error occurred while analyzing {repo_url}: {str(e)}")
    
    # Add help section at the bottom
    create_help_section()

if __name__ == '__main__':
    main()