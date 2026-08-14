import calendar
import datetime
import os
import re

import requests

TOKEN = os.environ['ACCESS_TOKEN']
USERNAME = os.environ.get('USER_NAME', 'madisonewebb')
HEADERS = {'authorization': 'token ' + TOKEN}

# Repos excluded from the Lines-of-Code count because they contain vendored
# or generated files that aren't representative of hand-written code.
EXCLUDED_LOC_REPOS = {'forge-dora-dashboard'}

STATIC = {
    'os': 'Windows 11, Linux, macOS',
    'host': 'Liatrio',
    'kernel': 'Forward Deployed Engineer',
    'ide': 'Cursor, Claude Code',
    'lang_programming': 'JavaScript, Python, SQL, C++, Go, Dart',
    'lang_computer': 'HTML, CSS, JSON, YAML, HCL',
    'hobbies_software': 'Home K8s Cluster, Game Server Hosting',
    'hobbies_hardware': '3D Printing, PC Hardware, Modding',
    'linkedin': 'linkedin.com/in/madisonewebb28',
    'discord': 'madi28',
    'email_personal': 'madiwebb28@gmail.com',
    'email_work': 'madison.webb@liatrio.com',
}

FONT = "font-family=\"'Consolas', 'Menlo', 'DejaVu Sans Mono', monospace\""

PALETTES = {
    'dark': dict(x=540, y0=163, dash='#3d444d', title='#58a6ff', key='#ffa657', dots='#484f58',
                 val='#c9d1d9', num='#79c0ff', add='#3fb950', dele='#f85149'),
    'light': dict(x=492, y0=148.6, dash='#d0d7de', title='#0969da', key='#953800', dots='#8c959f',
                  val='#24292f', num='#0550ae', add='#1a7f37', dele='#cf222e'),
}


def gql(query, variables):
    r = requests.post('https://api.github.com/graphql', json={'query': query, 'variables': variables}, headers=HEADERS)
    r.raise_for_status()
    data = r.json()
    if 'errors' in data:
        raise Exception(data['errors'])
    return data['data']


def user_info(username):
    q = '''query($login:String!){ user(login:$login){ id createdAt followers{totalCount} } }'''
    d = gql(q, {'login': username})['user']
    return d['id'], d['createdAt'], d['followers']['totalCount']


def account_age(created_at):
    created = datetime.datetime.strptime(created_at, '%Y-%m-%dT%H:%M:%SZ')
    now = datetime.datetime.utcnow()
    years = now.year - created.year
    months = now.month - created.month
    days = now.day - created.day
    if days < 0:
        months -= 1
        prev_month = now.month - 1 or 12
        prev_year = now.year if now.month != 1 else now.year - 1
        days += calendar.monthrange(prev_year, prev_month)[1]
    if months < 0:
        years -= 1
        months += 12

    def plural(n, word):
        return f"{n} {word}{'s' if n != 1 else ''}"
    return f"{plural(years, 'year')}, {plural(months, 'month')}, {plural(days, 'day')}"


def repos_and_stars(owner_affiliation, cursor=None, repos_acc=None, stars_acc=0):
    q = '''
    query($aff:[RepositoryAffiliation], $login:String!, $cursor:String){
      user(login:$login){
        repositories(first:100, after:$cursor, ownerAffiliations:$aff){
          totalCount
          edges{ node{ name nameWithOwner isFork stargazers{totalCount} } }
          pageInfo{ endCursor hasNextPage }
        }
      }
    }'''
    d = gql(q, {'aff': owner_affiliation, 'login': USERNAME, 'cursor': cursor})['user']['repositories']
    if repos_acc is None:
        repos_acc = []
    repos_acc.extend(d['edges'])
    stars_acc += sum(e['node']['stargazers']['totalCount'] for e in d['edges'])
    if d['pageInfo']['hasNextPage']:
        return repos_and_stars(owner_affiliation, d['pageInfo']['endCursor'], repos_acc, stars_acc)
    return d['totalCount'], repos_acc, stars_acc


def recursive_loc(owner, repo_name, owner_id, add=0, dele=0, cursor=None):
    q = '''
    query($repo:String!, $owner:String!, $cursor:String){
      repository(name:$repo, owner:$owner){
        defaultBranchRef{ target{ ... on Commit {
          history(first:100, after:$cursor){
            edges{ node{ ... on Commit { additions deletions } author{ user{ id } } } }
            pageInfo{ endCursor hasNextPage }
          }
        }}}
      }
    }'''
    d = gql(q, {'repo': repo_name, 'owner': owner, 'cursor': cursor})['repository']
    if not d['defaultBranchRef']:
        return add, dele
    hist = d['defaultBranchRef']['target']['history']
    for edge in hist['edges']:
        author = edge['node']['author']['user']
        if author and author['id'] == owner_id:
            add += edge['node']['additions']
            dele += edge['node']['deletions']
    if hist['pageInfo']['hasNextPage']:
        return recursive_loc(owner, repo_name, owner_id, add, dele, hist['pageInfo']['endCursor'])
    return add, dele


def total_commits_since(created_at):
    start = datetime.datetime.strptime(created_at, '%Y-%m-%dT%H:%M:%SZ')
    now = datetime.datetime.utcnow()
    total = 0
    cursor = start
    while cursor < now:
        window_end = min(cursor + datetime.timedelta(days=364), now)
        q = '''
        query($login:String!, $from:DateTime!, $to:DateTime!){
          user(login:$login){ contributionsCollection(from:$from, to:$to){ contributionCalendar{ totalContributions } } }
        }'''
        d = gql(q, {'login': USERNAME, 'from': cursor.strftime('%Y-%m-%dT%H:%M:%SZ'), 'to': window_end.strftime('%Y-%m-%dT%H:%M:%SZ')})
        total += d['user']['contributionsCollection']['contributionCalendar']['totalContributions']
        cursor = window_end
    return total


def fetch_live_data():
    owner_id, created_at, followers = user_info(USERNAME)
    uptime = account_age(created_at)
    owned_count, owned_repos, stars = repos_and_stars(['OWNER'])
    contrib_count, _, _ = repos_and_stars(['OWNER', 'COLLABORATOR', 'ORGANIZATION_MEMBER'])
    commits = total_commits_since(created_at)

    add_total, del_total = 0, 0
    for e in owned_repos:
        node = e['node']
        if node['isFork'] or node['name'] in EXCLUDED_LOC_REPOS:
            continue
        owner, name = node['nameWithOwner'].split('/')
        a, d = recursive_loc(owner, name, owner_id)
        add_total += a
        del_total += d

    return {
        'uptime': uptime,
        'repos': f'{owned_count}',
        'contrib': f'{contrib_count}',
        'stars': f'{stars}',
        'commits': f'{commits:,}',
        'followers': f'{followers}',
        'loc_total': f'{add_total - del_total:,}',
        'loc_add': f'{add_total:,}',
        'loc_del': f'{del_total:,}',
    }


def row(x, y, parts):
    inner = ''.join(f'<tspan fill="{fill}">{text}</tspan>' for fill, text in parts)
    return f'  <text x="{x}" y="{y}" {FONT} xml:space="preserve" font-size="16">{inner}</text>'


def kv(pal, y, label, value, dots=3, val_color=None):
    dot_str = ' ' + ('.' * dots) + ' ' if dots > 0 else ' '
    return row(pal['x'], y, [
        (pal['key'], f'. {label}: '),
        (pal['dots'], dot_str),
        (val_color or pal['val'], value),
    ])


def dual(pal, y, l1, v1, d1, l2, v2, d2):
    dot1 = ' ' + ('.' * d1) + ' '
    dot2 = ' ' + ('.' * d2) + ' '
    return row(pal['x'], y, [
        (pal['key'], f'. {l1}: '), (pal['dots'], dot1), (pal['num'], v1),
        (pal['dash'], ' | '),
        (pal['key'], f'. {l2}: '), (pal['dots'], dot2), (pal['num'], v2),
    ])


def header(pal, y, title, dash_len):
    return row(pal['x'], y, [
        (pal['dash'], '─'),
        (pal['title'], f' {title} '),
        (pal['dash'], '─' * dash_len),
    ])


def build_stats_block(pal, handle, data):
    y = pal['y0']
    lines = []
    lines.append(header(pal, y, f'{handle}@github', 40)); y += 20
    lines.append(kv(pal, y, 'OS', STATIC['os'], 24)); y += 20
    lines.append(kv(pal, y, 'Uptime', data['uptime'], 20)); y += 20
    lines.append(kv(pal, y, 'Host', STATIC['host'], 38)); y += 20
    lines.append(kv(pal, y, 'Kernel', STATIC['kernel'], 20)); y += 20
    lines.append(kv(pal, y, 'IDE', STATIC['ide'], 33)); y += 30
    lines.append(kv(pal, y, 'Languages.Programming', STATIC['lang_programming'], 5)); y += 20
    lines.append(kv(pal, y, 'Languages.Computer', STATIC['lang_computer'], 9)); y += 30
    lines.append(kv(pal, y, 'Hobbies.Software', STATIC['hobbies_software'], 8)); y += 20
    lines.append(kv(pal, y, 'Hobbies.Hardware', STATIC['hobbies_hardware'], 12)); y += 30
    lines.append(header(pal, y, 'Contact', 50)); y += 20
    lines.append(kv(pal, y, 'LinkedIn', STATIC['linkedin'], 16)); y += 20
    lines.append(kv(pal, y, 'Discord', STATIC['discord'], 36)); y += 20
    lines.append(kv(pal, y, 'Email.Personal', STATIC['email_personal'], 12)); y += 20
    lines.append(kv(pal, y, 'Email.Work', STATIC['email_work'], 20)); y += 30
    lines.append(header(pal, y, 'GitHub Stats', 43)); y += 20
    lines.append(dual(pal, y, 'Repos', data['repos'], 14, 'Stars', data['stars'], 15)); y += 20
    lines.append(dual(pal, y, 'Commits', data['commits'], 9, 'Followers', data['followers'], 11)); y += 20
    lines.append(kv(pal, y, 'Contributed', data['contrib'], 20, val_color=pal['num'])); y += 20
    lines.append(row(pal['x'], y, [
        (pal['key'], '. Lines of Code: '),
        (pal['dots'], ' .. '),
        (pal['num'], data['loc_total']),
        (pal['dash'], ' ( '),
        (pal['add'], f"+{data['loc_add']}"),
        (pal['dash'], ', '),
        (pal['dele'], f"-{data['loc_del']}"),
        (pal['dash'], ' )'),
    ]))
    return '\n'.join(lines)


CARD_WIDTH = 1260
CARD_HEIGHT = 630


def rebuild(path, handle, theme, data):
    with open(path) as f:
        content = f.read()
    ascii_lines = re.findall(r'  <text x="28".*?</text>', content)
    ascii_block = '\n'.join(ascii_lines)
    rect = re.search(r'<rect[^>]*/>', content).group(0)
    rect = re.sub(r'width="[\d.]+"', f'width="{CARD_WIDTH - 1}"', rect)
    rect = re.sub(r'height="[\d.]+"', f'height="{CARD_HEIGHT - 1}"', rect)
    svg_open = re.search(r'<svg[^>]*>', content).group(0)
    svg_open = re.sub(r'width="[\d.]+"', f'width="{CARD_WIDTH}"', svg_open)
    svg_open = re.sub(r'height="[\d.]+"', f'height="{CARD_HEIGHT}"', svg_open)
    svg_open = re.sub(r'viewBox="[^"]*"', f'viewBox="0 0 {CARD_WIDTH} {CARD_HEIGHT}"', svg_open)

    pal = PALETTES[theme]
    stats_block = build_stats_block(pal, handle, data)
    new_content = svg_open + '\n' + rect + '\n' + ascii_block + '\n' + stats_block + '\n</svg>\n'
    with open(path, 'w') as f:
        f.write(new_content)


if __name__ == '__main__':
    live = fetch_live_data()
    rebuild('dark_mode.svg', USERNAME, 'dark', live)
    rebuild('light_mode.svg', USERNAME, 'light', live)
    print('Card refreshed:', live)
