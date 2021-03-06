
import time
from tools import datalines
from tools import remove_invalid_char
import os
import shutil

from urllib.parse import unquote

from jinja2 import Template
import re

from tools import fix_md_title
from tools import fix_svg_image
from tools import fix_video_link
from tools import fix_code_lang
from tools import fix_image_alt
from fetcher import UrlType
from fetcher import parse_type

import tools
from tools import create_logger
log = create_logger(__file__)
log_error = create_logger(__file__ + '.error')

from markdown import markdown
from mdx_gfm import GithubFlavoredMarkdownExtension
import pygments


class Page:
  '''
  表达一个抓取后的页面, 不管抓取过程
                    -> Page 
  Watcher -> Task -|
                    -> FetcherAPI
  页面内容分为 元数据 + 文章主体 + 评论, 评论先放放
  Page.load(filepath)   返回一个读盘的页面
  Page.create(data) 返回一个新建 (从 fetcher 后的 data json) 的页面
  page.write()  存储页面
  page.render() 转为其他格式, rss, pdf 等, 用于 Exporter
  page.compare() 比对两个页面的区别

  以md文件为单位 Page 对应一个 json data
  Page data json struct:

    title
    folder
    watch_time
    version

    metadata 依据不同类型 Page 而定
      author
      topic
      question
      voteup
      thanks

    sections 如果包含 sections, 说明是从本地 md 加载得来, 需要还原内容和评论等

    文本形式为 (参考 Jekyll markdown)

        ---
        title:  title
        url:  url
        metadatakey1: value1
        metadatakey2: value2
        metadatakey3: value3
        ---

        # 标题

        ## 内容分段1 (如问题 / 引文)

        ### 文章内部标题1
        ### 文章内部标题2
        ### 文章内部标题3
        ### 文章内部标题4

        ## 内容分段2 (如回答 / 正文)

        ### 文章内部标题5
        ### 文章内部标题6

        ## 评论

      抓取文章中自带标题尽量降级到 `三级 title (###)` 以下


  '''
  def __init__(self, data):
    self.metadata = data['metadata']
    self.tmpl = ''  # should override
    self.data = {}  # should override

  def __str__(self):
    title = self.metadata['title']
    return '<Page #{1}> {2} (ver. {0.version}, {0.fetch_date}) '.format(self, id(self), title)

  def to_id(self):
    return '<Page #{}>'.format(id(self))

  @property
  def full_text(self):
    ''' 完整的 md 文本, 
        从本地文件 load 回来的 Page 的 data 里面自带 full_text
        新生成的 Page 对象需要 render 得到 full_text'''
    return self.data.get('full_text') or self.render(type='localfile')
  
  @property
  def sections(self):
    ''' 截取页面中如 ## 评论: ## 正文: 的内容 '''
    return tools.sections(self.full_text, is_title=lambda line: line.startswith('##'))

  @property    # 一些常用属性的快捷方式
  def version(self): return self.metadata['version']
  @property
  def create_date(self): return self.metadata.get('create_date') or self.metadata.get('edit_date')  # 字符串格式
  @property
  def edit_date(self): return self.metadata.get('edit_date') or self.metadata.get('create_date')
  @property
  def fetch_date(self): return self.metadata.get('fetch_date')
  @property
  def filename(self): 
    name = remove_invalid_char(self.metadata['title']) + '.md'
    enlen = lambda t: tools.encode_len(t, encode='utf-8')
    if tools.is_linux() and enlen(name) > 255:  
      # Linux 视为 ext4 格式, 需要 filename 不超过 255 字符
      # 找 name 中最长的一个片段, 缩减至符合字数要求
      parts = name.split(' ')
      long_part_index = parts.index(max(parts, key=enlen))
      limit = enlen(parts[long_part_index]) - (enlen(name) - 255)
      parts[long_part_index] = tools.truncate(parts[long_part_index], limit=limit, encode='utf-8')
      return ' '.join(parts)
    else:
      return name
  @property
  def url(self): return self.metadata['url']
  @property
  def folder(self): return self.metadata['folder']



  @classmethod
  def create(cls, data):
    ''' 创建 Page usage:
          data_json['metadata']['url'] = self.url
          data_json['folder'] = self.option['folder']
          data_json['metadata']['version'] = self.version + 1
          page = Page.create(data_json)
    '''
    url = data['metadata']['url']
    page_type = parse_type(url)
    if page_type == UrlType.ZhihuColumnPage:
      return ZhihuColumnPage(data)

    if page_type == UrlType.ZhihuAnswerPage:
      return ZhihuAnswerPage(data)

    if page_type == UrlType.WeixinArticlePage:
      return WeixinArticlePage(data)

    if page_type == UrlType.V2exPage:
      return V2exPage(data)
    raise NotImplementedError('Page.request: cannot reg type {}'.format(url))


  @staticmethod
  def convert_dict(metadata_txt):
    d = {}
    for line in metadata_txt.splitlines():
      if line.strip():
        k, v = line.strip().split(':', 1)
        d[k.strip()] = v.strip()
    return d

  @classmethod
  def load(cls, path):
    ''' 从磁盘加载 Page
        用于比对页面是否有变化, 以及生成 RSS 等
        比对页面是否有变化时, 只需要加载 title content 等少数内容, 评论等可以不加载 '''
    if not os.path.exists(path):
      raise ValueError('{} not found'.format(path))
    txt = tools.text_load(path)

    metadata = Page.convert_dict(txt.split('---')[1].strip())
    data = {'folder': os.path.dirname(path), 
            'metadata': metadata, 
            'full_text': txt,
            'from_disk': True,  # 从磁盘加载 Page 增加这个 key
            } 
    return cls.create(data)


  def is_changed(self, other):
    ''' 比对一个page对象是否有变化 '''
    raise NotImplementedError # return self.metadata['title'] == other.metadata['title'] and self.data['content'] == other.data['content']

  @property
  def last_page_version(self):
    ''' 寻找上一次的页面存档 '''
    guess_path = os.path.join(self.folder, self.filename)
    if os.path.exists(guess_path):
      return Page.load(guess_path)
    else:
      return None

  def write(self):
    '''存盘'''
    if not os.path.exists(self.folder):
      raise FileNotFoundError('can not open folder {}'.format(self.folder))
    save_path = os.path.join(self.folder, self.filename)
    # overwrite = 'update file' if os.path.exists(save_path) else 'create file'
      # log('warning! already exist {}'.format(save_path))
    with open(save_path, 'w', encoding='utf-8') as f:
      f.write(self.render(type='localfile'))
      # log('write {} done ({})'.format(save_path, overwrite))

    # if fetch_images:
    #   # 本地存储, 需要抓取所有附图 TODO
    #   fetch_images_for_markdown(save_path)
    # return save_path

  def render(self, type='localfile'):
    if type == 'localfile':
      tmpl = tools.text_load(self.tmpl)
      rendered = Template(tmpl).render(data=self.data)
      return rendered
    else:
      raise NotImplementedError

  def to_html(self, cut=0):
    ''' 转换为 html 用于输出 RSS 等
        必须有 data['full_text'] 才能 to_html() '''
    full_text = self.full_text
    if cut and len(full_text) > cut:
      full_text = full_text[:cut] + f' ... (共 {len(full_text)} 字)'

    # TODO: 图片需要 alt
    
    # 将代码段 ```js\n......``` 的内容事先转成带 style="xxx" 样式的 html
    # 此时文档仍为 markdown, 内嵌部分 html 代码
    def replacer(match):
      lexer_name = match.group(1) or 'js'  # 未在 md 里指明时, 默认用 js 语法高亮
      code_block = match.group(2)
      with_style = convert_code_highlighting_style(code_block, lexer_name)
      return f"\n\n{with_style}\n\n"

    def convert_code_highlighting_style(code_block, lexer_name):
      try:
        lexer = pygments.lexers.get_lexer_by_name(lexer_name)
      except pygments.util.ClassNotFound:
        lexer = pygments.lexers.get_lexer_by_name('js')
      formatter = pygments.formatters.HtmlFormatter(linenos=False, noclasses=True)  # noclasses: use style instead of class, linenos 没用, 添加了行号会渲染成 table, 碍事
      return pygments.highlight(code_block, lexer, formatter)

    pat = re.compile(r'\`\`\`(.*?)\n(.+?)\`\`\`', re.DOTALL)  
    full_text = re.sub(pat, replacer, full_text)
    # end of 将代码段...

    html = markdown(full_text, output_format='html5', extensions=[GithubFlavoredMarkdownExtension()])
    return html

  def postprocess(self, data):
    ''' 处理 # 标题降级, 
        LATEX, 
        图片视频链接修正,
        代码判断语言种类和染色
        等等'''

    raise NotImplementedError


# =========================================================
# =================== end of class Page ===================
# =========================================================



































class ZhihuColumnPage(Page):
  '''抓取Zhihu专栏的一篇文章
  专栏文章 added 属性:
    metadata
      author
      topic
      voteup
      thanks
      columnname
    content: 正文:
    comment:
  '''

  def __init__(self, data):

    super().__init__(data)
    self.tmpl = 'crawler/zhihu_column_page.jinja2'
    if data.get('from_disk'):
      self.data = data
    else:
      data = self.postprocess(data)
      self.data = data

  @property
  def content(self):
    for (_, title), value in self.sections.items():
      if '## 正文:' == title: return value
    raise ValueError('section `正文` not found')

  def is_changed(self, other):
    ''' 比对一个ZhihuColumnPage对象是否有变化 '''
    if not other: return True
    content1 = self.content
    content2 = other.content
    # if content1 != content2:
    #   log(tools.compare_text(content1.strip(), content2.strip()))
    title1 = self.metadata['title']
    title2 = other.metadata['title']
    return (title1 != title2) or (content1 != content2)

  def postprocess(self, data):
    content = fix_md_title(data['content'])
    content = fix_video_link(content)
    content = fix_svg_image(content)
    content = fix_image_alt(content)
    content = fix_code_lang(content)
    data['content'] = content
    return data



class ZhihuAnswerPage(Page):
  '''抓取Zhihu一篇回答

  回答 added 属性:
    metadata
      author
      voteup
      thanks

    question desc: 问题和描述:
    topic: 话题:
    answer: 回答:
    comment:

  '''

  def __init__(self, data):
    super().__init__(data)
    self.tmpl = 'crawler/zhihu_answer_page.jinja2'

    if data.get('from_disk'):  # from local load text
      self.data = data
    else:
      data = self.postprocess(data)
      self.data = data

  @property
  def answer(self):
    for (_, title), value in self.sections.items():
      if '## 回答:' == title: return value
    raise ValueError('section `回答` not found')
  @property
  def question_description(self):
    for (_, title), value in self.sections.items():
      if '## 问题描述:' == title: return value
    raise ValueError('section `问题描述` not found')

  def is_changed(self, other):
    ''' 比对一个ZhihuAnswerPage对象是否有变化 '''
    if not other: return True
    title1 = self.metadata['title']
    title2 = other.metadata['title']
    answer1 = self.answer
    answer2 = other.answer
    qdesc1 = self.question_description
    qdesc2 = other.question_description
    return (title1 != title2) or (qdesc1 != qdesc2) or (answer1 != answer2)

  def postprocess(self, data):
    answer = fix_md_title(data['answer'])
    answer = fix_video_link(answer)
    answer = fix_svg_image(answer)
    answer = fix_image_alt(answer)
    answer = fix_code_lang(answer)
    data['answer'] = answer
    return data







class WeixinArticlePage(Page):
  '''抓取微信公众号页面'''
  def __init__(self, data):
    super().__init__(data)
    self.tmpl = 'crawler/weixin_article_page.jinja2'
    if data.get('from_disk'):
      self.data = data
    else:
      data = self.postprocess(data)
      self.data = data

  @property
  def content(self):
    for (_, title), value in self.sections.items():
      if '## 正文:' == title: return value
    raise ValueError('section `正文` not found')

  def is_changed(self, other):
    ''' 比对一个ZhihuColumnPage对象是否有变化 '''
    if not other: return True
    content1 = self.content
    content2 = other.content
    # if content1 != content2:
    #   log(tools.compare_text(content1.strip(), content2.strip()))
    title1 = self.metadata['title']
    title2 = other.metadata['title']
    return (title1 != title2) or (content1 != content2)

  def postprocess(self, data):
    # content = fix_md_title(data['content'])
    # content = fix_video_link(content)
    # content = fix_svg_image(content)
    # content = fix_image_alt(content)
    # content = fix_code_lang(content)
    # data['content'] = content
    return data

class V2exPage(Page):
  def __init__(self, data):
    super().__init__(data)
    self.tmpl = 'crawler/v2ex_page.jinja2'
    if data.get('from_disk'):
      self.data = data
    else:
      data = self.postprocess(data)
      self.data = data
      
  def postprocess(self, data):
    # content = fix_md_title(data['content'])
    # content = fix_video_link(content)
    # content = fix_svg_image(content)
    # content = fix_image_alt(content)
    # content = fix_code_lang(content)
    # data['content'] = content
    return data