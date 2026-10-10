"""One-shot publisher for the exact parent-reviewed October 10 site-page package."""
from html.parser import HTMLParser
import json
import re

import reviewed_publish as rp
from site_pages_transport import COPY, PLANNED, Preflight, digest, menu_ids, PATTERNS

COPY_SHA = 'a9d53b76b05ba1b734eea0774ad581be729757e0bf92d9d4ea8e227708156adc'


class SafeCopy(HTMLParser):
    def handle_starttag(self, tag, attrs):
        rp.require(tag in {'p','h2','ul','li','a'}, 'Unapproved site-page markup')
        rp.require((tag == 'a' and len(attrs) == 1 and attrs[0][0] == 'href') or not attrs,
                   'Unapproved site-page attributes')
        if tag == 'a':rp.url(attrs[0][1])
    def handle_comment(self, data):
        raise rp.Guard('Reviewed page copy cannot carry an ownership marker')


def load_copy():
    path = rp.scoped_path(COPY, 'reviewed/site-pages')
    rp.require(rp.sha(path.read_bytes()) == COPY_SHA, 'Exact parent-reviewed site copy changed')
    data = json.loads(path.read_text())
    rp.fields(data, {'draft_only','pages','author_bio_text','fact_ledger','publication_notes'})
    rp.require(data['draft_only'] is True and len(data['pages']) == 4, 'Unexpected reviewed drafting artifact')
    for p, plan in zip(data['pages'], PLANNED):
        rp.fields(p, {'title','slug','excerpt','content','meta','status','comment_status','ping_status'})
        rp.require(p['title'] == plan['title'] and p['slug'] == plan['slug'] and p['status'] == 'publish' and
                   p['comment_status'] == p['ping_status'] == 'closed', 'Unapproved site-page identity or status')
        rp.fields(p['meta'], {'_seopress_titles_title','_seopress_titles_desc'})
        rp.require(p['meta']['_seopress_titles_desc'] == p['excerpt'], 'Reviewed SEO description differs')
        SafeCopy().feed(p['content'])
    rp.text(data['author_bio_text'], 1000)
    return data


class MenuDOM(HTMLParser):
    def __init__(self):
        super().__init__();self.stack=[];self.nodes={}
    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        if tag=='li':
            match=re.fullmatch(r'menu-item-(\d+)',attrs.get('id',''))
            identifier=int(match[1]) if match else 0
            parent=next((i for i in reversed(self.stack) if i),0)
            self.stack.append(identifier)
            if identifier:self.nodes.setdefault(identifier,[]).append({'parent':parent,'links':[]})
        elif tag=='a' and self.stack and self.stack[-1]:
            self.nodes[self.stack[-1]][-1]['links'].append(attrs.get('href'))
    def handle_endtag(self,tag):
        if tag=='li' and self.stack:self.stack.pop()


class Publisher(Preflight):
    def __init__(self, session, package, baseline, public_get=None):
        if public_get is None:super().__init__(session)
        else:super().__init__(session, public_get)
        self.package=package;self.baseline=baseline;self.permitted=None;self.owned_ids=set();self.owned_copies={};self.owned_nav=[]
        self.author_id=baseline['author']['id'];self.primary=baseline['primary_navigation']['menu_id']

    def api(self, method, endpoint, **kwargs):
        if method == 'POST':
            rp.require(self.permitted == (endpoint, kwargs.get('json')) and set(kwargs) == {'json'},
                       'Unapproved site-page write')
            return rp.Transport.api(self, method, endpoint, **kwargs)
        return super().api(method, endpoint, **kwargs)

    def body(self, p):
        key=next(x['key'] for x in PLANNED if x['slug']==p['slug'])
        return p['content']+'\n<!-- pontotoc-site-page:'+key+':'+COPY_SHA+' -->'

    def create_payload(self, p):
        return {k:p[k] for k in ('slug','title','excerpt','comment_status','ping_status','meta')} | {
            'content':self.body(p),'status':'draft','parent':0,'author':self.author_id}

    def write(self, endpoint, payload):
        allowed = endpoint=='pages' and any(payload==self.create_payload(p) for p in self.package['pages'])
        allowed |= endpoint=='users/me' and payload=={'description':self.package['author_bio_text']}
        if re.fullmatch(r'pages/\d+', endpoint) and int(endpoint.split('/')[-1]) in self.owned_ids:
            allowed |= payload=={'status':'publish'} or payload=={'meta':self.owned_copies[int(endpoint.split('/')[-1])]['meta']}
        if endpoint=='menu-items':
            page=self.owned_copies.get(payload.get('object_id'))
            index=self.package['pages'].index(page) if page else -1
            about=next((i for i in self.owned_nav if self.owned_copies[i['object_id']]['slug']=='about'),None)
            allowed = bool(page and set(payload)=={'title','type','object','object_id','menus','parent','menu_order','status'} and
                payload['title']==page['title'] and payload['type']=='post_type' and payload['object']=='page' and
                payload['menus']==self.primary and payload['status']=='publish' and
                payload['parent']==(0 if index==0 else about['id'] if about else -1) and
                payload['menu_order']==self.baseline['primary_navigation']['next_menu_order']+index)
        rp.require(allowed, 'Site-page write exceeds reviewed scope')
        self.permitted=(endpoint,payload)
        try:return self.api('POST',endpoint,json=payload)
        finally:self.permitted=None

    def owned(self, pages):
        owned={}
        for p in self.package['pages']:
            key=next(x['key'] for x in PLANNED if x['slug']==p['slug'])
            matching=[r for r in pages if '<!-- pontotoc-site-page:'+key+':' in r['content']['raw']]
            rp.require(len(matching)<=1,'Ambiguous site-page ownership')
            if matching:
                row=matching[0]
                rp.require(row['content']['raw']==self.body(p) and row['title']['raw']==p['title'] and
                    row['excerpt']['raw']==p['excerpt'] and row['slug']==p['slug'] and row['status'] in {'draft','publish'} and
                    row.get('parent')==0 and row.get('author')==self.author_id and row.get('featured_media')==0 and
                    row.get('comment_status')==row.get('ping_status')=='closed' and not row.get('password') and
                    all(row.get('meta',{}).get(k)==v or (row['status']=='draft' and row.get('meta',{}).get(k) in {None,''})
                        for k,v in p['meta'].items()),
                    'Existing owned page differs; no overwrite')
                owned[p['slug']]=row
        ids={r['id'] for r in owned.values()}
        for row in pages:
            if row['id'] in ids:continue
            identity=rp.plain(row['title']['raw'])+' '+row['slug'].replace('-',' ')
            headings=' '.join(rp.plain(h) for h in re.findall(r'<h[1-6]\b[^>]*>(.*?)</h[1-6]>',row['content']['raw'],re.I|re.S))
            for plan in PLANNED:
                rp.require(row['slug']!=plan['slug'] and not re.search(PATTERNS[plan['key']],identity+' '+headings,re.I),
                           'Conflicting existing topic page; no replacement or duplicate')
        self.owned_ids=ids
        self.owned_copies={row['id']:next(p for p in self.package['pages'] if p['slug']==slug) for slug,row in owned.items()}
        return owned

    def state(self):
        me,_=self.api('GET','users/me',params={'context':'edit','_fields':'id,name,description,link,capabilities'})
        rp.require(me.get('id')==self.author_id and me.get('name')=='Jon Myers' and
                   me.get('link')==self.baseline['author']['archive_url'] and
                   all(me.get('capabilities',{}).get(k) is True for k in self.baseline['account_capabilities']),
                   'Author identity or capabilities drifted')
        rp.require(rp.sha(me['description'].encode())==self.baseline['author']['description_sha256'] or
                   me['description']==self.package['author_bio_text'],'Existing author biography changed; no overwrite')
        pages=self.all_status('pages');owned=self.owned(pages)
        rp.require(digest(sorted([p for p in pages if p['id'] not in self.owned_ids],key=lambda p:p['id']))==
                   self.baseline['page_snapshot_sha256'],'Unrelated existing pages changed')
        items=self.all_status('menu-items')
        own_items=[i for i in items if i.get('type')=='post_type' and i.get('object')=='page' and
                   i.get('object_id') in self.owned_ids and self.primary in menu_ids(i)]
        self.owned_nav=own_items
        other=[i for i in items if i not in own_items]
        rp.require(digest(sorted(other,key=lambda i:i['id']))==self.baseline['all_menu_items_snapshot_sha256'],
                   'Existing menu items changed or partial navigation write needs reconciliation')
        locations,_=self.api('GET','menu-locations');menu,_=self.api('GET','menus/'+str(self.primary),params={'context':'edit'})
        # Core's term count increases with our new published items. All settings
        # and the original term count remain protected by the preflight digest.
        menu=dict(menu)
        if 'count' in menu:
            rp.require(isinstance(menu['count'],int),'Invalid primary menu count')
            menu['count']-=sum(i['status']=='publish' for i in own_items)
        rp.require(digest(locations)==self.baseline['primary_navigation']['locations_sha256'] and
                   digest(menu)==self.baseline['primary_navigation']['menu_sha256'],'Primary menu assignment or settings changed')
        target_urls={rp.BASE+'/'+p['slug']+'/' for p in self.package['pages']}
        rp.require(not any(self.primary in menu_ids(i) and i.get('url') in target_urls for i in other),
                   'Existing menu link already targets a proposed page')
        return me,owned,own_items

    def source_links(self):
        targets={rp.BASE+'/'+p['slug']+'/' for p in self.package['pages']}
        links={u for p in self.package['pages'] for u in rp.parsed(p['content']).links}-targets
        # Preserve approved hrefs. Public publisher aliases may redirect; never attach credentials.
        for link in sorted(links):
            current=link
            for attempt in range(4):
                rp.url(current)
                response=self.public_get(current,timeout=rp.TIMEOUT,allow_redirects=False)
                if response.status_code==200:break
                rp.require(response.status_code in {301,302,307,308} and attempt<3,
                           'Reviewed page source or contact link unavailable')
                from urllib.parse import urljoin
                current=urljoin(current,response.headers.get('Location',''))
            rp.require(response.status_code==200,'Reviewed link redirect chain failed')

    def run(self, apply=True):
        rp.require(self.baseline.get('verified_preflight') is True and self.baseline.get('ready_for_copy_review') is True and
                   all(self.baseline.get('seo_meta_writable',{}).values()),'Site-page preflight is not ready')
        self.source_links()
        me,owned,_=self.state()
        schema,_=self.api('OPTIONS','pages')
        props=schema.get('schema',{}).get('properties',{}).get('meta',{}).get('properties',{})
        rp.require(all(props.get(k,{}).get('type')=='string' and not props[k].get('readonly',props[k].get('readOnly',False))
                   for k in ['_seopress_titles_title','_seopress_titles_desc']),'Reviewed page SEO metadata not writable')
        if apply:
            for p in self.package['pages']:
                if p['slug'] not in owned:
                    response=self.public_get(rp.BASE+'/'+p['slug']+'/',timeout=rp.TIMEOUT,allow_redirects=False)
                    rp.require(response.status_code==404,'Proposed page public route occupied')
                    self.write('pages',self.create_payload(p))
                    owned=self.owned(self.all_status('pages'))
                    rp.require(p['slug'] in owned,'Created page not reconciled; stop')
            _,owned,_=self.state()
            for p in self.package['pages']:
                row=owned[p['slug']]
                if row['status']=='draft':
                    latest,_=self.api('GET','pages/'+str(row['id']),params={'context':'edit'})
                    rp.require(latest==row,'Owned draft changed before publication')
                    if any(row.get('meta',{}).get(k)!=v for k,v in p['meta'].items()):
                        self.write('pages/'+str(row['id']),{'meta':p['meta']})
                        latest,_=self.api('GET','pages/'+str(row['id']),params={'context':'edit'})
                        rp.require(all(latest.get('meta',{}).get(k)==v for k,v in p['meta'].items()) and
                                   self.owned(self.all_status('pages')),'Partial SEO metadata did not reconcile')
                    self.write('pages/'+str(row['id']),{'status':'publish'})
            me,owned,nav=self.state()
            if me['description']!=self.package['author_bio_text']:
                latest,_=self.api('GET','users/me',params={'context':'edit','_fields':'id,name,description,link,capabilities'})
                rp.require(latest==me,'Author changed during reviewed publication')
                self.write('users/me',{'description':self.package['author_bio_text']})
            about_id=0
            for index,p in enumerate(self.package['pages']):
                _,owned,nav=self.state()
                row=owned[p['slug']]
                expected={'title':p['title'],'type':'post_type','object':'page','object_id':row['id'],
                          'menus':self.primary,'parent':0 if index==0 else about_id,
                          'menu_order':self.baseline['primary_navigation']['next_menu_order']+index,'status':'publish'}
                matched=[i for i in nav if i['object_id']==row['id']]
                rp.require(len(matched)<=1,'Duplicate reviewed page navigation')
                if not matched:
                    self.write('menu-items',expected)
                    _,owned,nav=self.state();matched=[i for i in nav if i['object_id']==row['id']]
                rp.require(len(matched)==1 and all((matched[0]['title']['raw'] if k=='title' else matched[0].get(k))==v
                    for k,v in expected.items()),'Reviewed navigation differs; no overwrite')
                if index==0:about_id=matched[0]['id']
        report=self.verify()
        report['read_only']=not apply
        return report

    def verify(self):
        me,owned,nav=self.state()
        rp.require(len(owned)==len(nav)==4 and me['description']==self.package['author_bio_text'],
                   'Reviewed site-page project is incomplete')
        receipts=[]
        for p in self.package['pages']:
            row=owned[p['slug']];target=rp.BASE+'/'+p['slug']+'/'
            rp.require(row['status']=='publish' and row['link']==target,'Reviewed page not published at approved URL')
            rest=self.public(rp.BASE+'/wp-json/wp/v2/pages/'+str(row['id'])).json()
            rp.require(rest.get('status')=='publish' and rp.public_text(rest['title']['rendered'])==rp.public_text(p['title']) and
                       rp.public_text(rest['content']['rendered'])==rp.public_text(p['content']) and
                       rp.public_text(rest['excerpt']['rendered'])==rp.public_text(p['excerpt']),'Reviewed public REST page differs')
            response=self.public(target);page=rp.parsed(response.text)
            rp.require(page.canonicals==[target] and rp.public_text(''.join(page.title_words))==rp.public_text(p['meta']['_seopress_titles_title']) and
                       [rp.public_text(h) for h in page.headlines]==[rp.public_text(p['title'])] and
                       len(page.descriptions)==1 and rp.public_text(page.descriptions[0])==rp.public_text(p['excerpt']),
                       'Reviewed page SEO rendering differs')
            rp.require('noindex' not in response.headers.get('X-Robots-Tag','').lower() and
                       not any('noindex' in x.lower() for x in page.robots),'Reviewed page marked noindex')
            expected_links=set(rp.parsed(p['content']).links)
            rp.require(expected_links<=set(page.links) and expected_links<=set(rp.parsed(rest['content']['rendered']).links) and
                       all(rp.public_text(text) in rp.public_text(response.text) for text in re.findall(r'<(?:p|li)>(.*?)</(?:p|li)>',p['content'],re.S)),
                       'Reviewed page body or cross-links missing')
            for link in expected_links:
                if link.startswith(rp.BASE+'/'):self.public(link)
            receipts.append({'id':row['id'],'url':target,'title':p['title'],'verified':True})
        home=self.public(rp.BASE+'/').text;dom=MenuDOM();dom.feed(home)
        about=next(i for i in nav if i['object_id']==owned['about']['id'])
        for p in self.package['pages']:
            item=next(i for i in nav if i['object_id']==owned[p['slug']]['id'])
            parent=0 if p['slug']=='about' else about['id']
            rp.require(any(n['parent']==parent and rp.BASE+'/'+p['slug']+'/' in n['links'] for n in dom.nodes.get(item['id'],[])),
                       'Reviewed primary navigation absent from rendered theme')
        for i in self.baseline['primary_navigation']['existing_root_links']:
            rp.require(any(i['url'] in n['links'] for n in dom.nodes.get(i['id'],[])),'Existing rendered root menu link missing')
        public_author=self.public(rp.BASE+'/wp-json/wp/v2/users/'+str(self.author_id)).json()
        rp.require(public_author.get('description')==self.package['author_bio_text'],'Saved author biography is not public in REST')
        archive=self.public(me['link']).text
        article,_=self.api('GET','posts/6010',params={'_fields':'link'})
        article_html=self.public(article['link']).text
        bio=rp.public_text(self.package['author_bio_text'])
        return {'verified':True,'copy_sha256':COPY_SHA,'pages':receipts,'preserved_existing_pages_and_menu_items':True,
                'navigation_verified':True,'primary_menu_id':self.primary,'new_menu_item_ids':sorted(i['id'] for i in nav),
                'author_bio':{'saved_and_public_rest_verified':True,'displayed_on_author_archive':bio in rp.public_text(archive),
                              'displayed_on_pepa_article':bio in rp.public_text(article_html),'biography_page_verified':True},
                'read_only':True}
