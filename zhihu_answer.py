﻿

import time
from pylon import puts
from pylon import datalines

import os
import shutil
import html2text
from pylon import enumrange
# import time
import datetime

from zhihu_oauth import ZhihuClient
from zhihu_oauth.zhcls.utils import remove_invalid_char
from jinja2 import Template
import re

import urllib.request


class ZhihuParseError(Exception):
  pass




TOKEN_FILE = 'token.pkl'
client = ZhihuClient()
client.load_token(TOKEN_FILE)


def zhihu_content_html2md(html):
  h2t = html2text.HTML2Text()
  h2t.body_width = 0
  r = h2t.handle(html).strip()
  r = '\n'.join(p.rstrip() for p in r.split('\n'))
  return re.sub('\n{4,}', '\n\n\n', r)


def parse_json_date(n):
  return str(datetime.datetime.fromtimestamp(n))


def valuable_conversations(answer, limit=10):
  '''
  return [[comment, comment...], ...]
  replies12 = list(c12.replies) # 所有回复本评论的评论, 第一条为本评论
  [print(r.author.name, r.content) for r in replies12]

  # 玄不救非氪不改命 可以用马列主义指导炒房嘛，郁闷啥呢？
  # Razor Liu 你觉得能问出这话的会是有钱炒房的阶级么...
  # 暗黑的傀儡师 思路很新颖，就是把劳动力市场看的太简...


  g12 = list(c12.conversation)  # 包含该评论的对话, 从最开始到结束
  [print(r.author.name, r.content) for r in g12]
  # Razor Liu 看不到武装革命可能性的情况下,读马列是不是会越读越郁闷?
  # 玄不救非氪不改命 可以用马列主义指导炒房嘛，郁闷啥呢？
  # Razor Liu 你觉得能问出这话的会是有钱炒房的阶级么...
  '''
  def _parse_comment(comment):
    reply_to_author = ' 回复 **{}**'.format(comment.reply_to.name) if comment.reply_to else ''
    vote_count = '  ({} 赞)'.format(comment.vote_count) if comment.vote_count else ''
    content = zhihu_content_html2md(comment.content).strip()
    if '\n' in content:
      content = '\n\n' + content
    text = '**{}**{}: {}{}\n\n'.format(comment.author.name, reply_to_author, content, vote_count)
    return text


  all_comments = list(answer.comments)
  while limit:
    top_voteup_comment = max(all_comments, key=lambda x: x.vote_count)
    if top_voteup_comment.vote_count < 3:
      break
    conversation = list(top_voteup_comment.conversation)
    conversation_ids = [c.id for c in conversation]
    all_comments = [c for c in all_comments if c.id not in conversation_ids]
    yield [_parse_comment(comment) for comment in conversation]
    limit -= 1







def fill_template(author=None, topics=None, motto=None,
                  title=None, question_details=None, content=None,
                  voteup_count=None, thanks_count=None,
                  conversations=None,
                  count=None, url=None,
                  create_date=None, edit_date=None, fetch_date=None,
                  ):

  tmpl_string = '''

# {{title}}

**话题**: {{topics}}

{%- if question_details %}
**Description**:

{{question_details}}
{% endif %}

    author: {{author}} {{motto}}
    voteup: {{voteup_count}} 赞同
    thanks: {{thanks_count}} 感谢
    create: {{create_date}}
    edit:   {{edit_date}}
    fetch:  {{fetch_date}}
    count:  {{count}} 字
    url:    {{url}}

{{content}}


{% if conversations %}
### Top Comments

{%- for conversation in conversations %}
{%- for comment in conversation %}
{{comment}}
{% endfor %}
-
{% endfor %}
{% endif %}



------------------

from: [{{url}}]()

'''

  return Template(tmpl_string).render(**locals())






def fetch_zhihu_answer(answer_url):
  time.sleep(1)

  answer = client.from_url(answer_url)
  # answer = client.answer(answer)
  author = answer.author
  question = answer.question

  try:
    content = answer.content
  except AttributeError:
    msg = 'cannot parse answer.content: {} {}'
    raise ZhihuParseError(msg.format(answer.question.title, answer_url))




  answer_body = zhihu_content_html2md(content)
  motto = '({})'.format(author.headline) if author.headline else ''
  question_details = zhihu_content_html2md(question.detail).strip()
  title = question.title + ' - ' + author.name + '的回答'
  topics = ', '.join(t.name for t in question.topics)






  t = fill_template(author=author.name,
                    motto=motto,
                    topics=topics,
                    title=title,
                    question_details=question_details,
                    content=answer_body,
                    voteup_count=answer.voteup_count,
                    thanks_count=answer.thanks_count,
                    # conversations=valuable_conversations(answer),
                    conversations=None,
                    count=len(answer_body),
                    url=answer_url,
                    create_date=parse_json_date(answer.created_time),
                    edit_date=parse_json_date(answer.updated_time),
                    fetch_date=time.strftime('%Y-%m-%d'),
                    )

  return {'title': title, 'content': t}






def save_answer(answer_url, folder='test', overwrite=True):
  if isinstance(answer_url, str):
    answer = client.from_url(answer_url)
    # answer = client.answer(answer)
  author = answer.author
  question = answer.question
  save_path = folder + '/' + remove_invalid_char(question.title + ' - ' + author.name + '的回答.md')
  if not overwrite and os.path.exists(save_path):
    puts('answer_md_file exist! save_path')
    return

  data = fetch_zhihu_answer(answer_url=answer_url)

  with open(save_path, 'w', encoding='utf8') as f:
    f.write(data['content'])
    puts('write save_path done')

  markdown_prettify(save_path)  # 去除 html2text 转换出来的 strong 和 link 的多余空格
  fetch_images_for_markdown_file(save_path)  # get images in markdown
  return save_path



def fetch_image(url, ext, markdown_file, image_counter):
  '''
  需要区分 全路径 和 相对引用
  需要转换每个 md 的附件名
  需要附件名编号'''
  if '.zhimg.com' not in url:
    print('  exotic url: ', url)
    return url
  # name = url.split('/')[-1]
  # nonlocal image_counter
  image_counter.append(1)
  image_index = str(len(image_counter))
  if len(image_index) == 1:
    image_index = '0' + image_index

  folder = os.path.dirname(markdown_file)
  basename = os.path.basename(markdown_file)[:-3]
  image_fullname = folder + '/' + basename + image_index + ext
  image_name = basename + image_index + ext

  if os.path.exists(image_fullname):
    print('  existed: ', url)
    return image_name

  print('    fetching', url)
  data = urllib.request.urlopen(url).read()
  with open(image_fullname, "wb") as f:
    f.write(data)
  return image_name



def fetch_images_for_markdown_file(markdown_file):
  with open(markdown_file, 'r', encoding='utf-8') as f:
    text = f.read()

  if 'whitedot.jpg' in text:
    print("'whitedot.jpg' in text")
    if not markdown_file.endswith('whitedot'):
      shutil.move(markdown_file, markdown_file + '.whitedot')
    return False

  # print('start parsing md file: ' + markdown_file.split('/')[-1])
  image_counter = []
  replacer = lambda m: fetch_image(url=m.group(0),
                                   ext=m.group(2),
                                   markdown_file=markdown_file,
                                   image_counter=image_counter)

  text2, n = re.subn(r'(https?://pic[^()]+(\.jpg|\.png|\.gif))', replacer, text)
  if n > 0:
    with open(markdown_file, 'w', encoding='utf-8') as f:
      f.write(text2)
    print('parsing md file done:  ' + markdown_file.split('/')[-1])
  else:
    print('no pictures downloaded:' + markdown_file.split('/')[-1])


from urllib.parse import unquote



def markdown_prettify(path, prefix=''):

  with open(path, encoding='utf-8') as f:
    lines = f.readlines()

  # drop extra space in link syntax
  # eg. [ wikipage ](http://.....) => [wikipage](http://.....)
  # eg2 [http://www.  businessanalysis.cn/por  tal.php ](http://www.businessanalysis.cn/portal.php)
  pattern_hyperlink = re.compile(r'\[ (.+?) \](?=\(.+?\))')

  def hyperlink_replacer(mat):
    r = mat.group(1).strip()
    print(r)
    if r.startswith('http'):
      r = re.sub(r'^https?:\/\/(www\.)?  ', '', r)
      r = r.replace(' ', '')
      # r = mat.group(1).replace('http://www.  ', '').replace('http://  ', '').replace(' ', '')
      if r.endswith('/'):
        r = r[:-1]
      if r.endswith('__'):
        r = r[:-2] + '...'
    else:
      if r.endswith(' _ _'):
        r = r[:-4] + '...'
      if r.endswith('__'):
        r = r[:-2]
    return '[{}]'.format(r)

  # drop extra space around strong tag
  pattern_strong = re.compile(r'\*\* (.+?) \*\*')
  replace_strong = lambda m: '** 回复 **' if m.group(1) == '回复' else '**'+m.group(1)+'**'

  # fix tex syntax use zhihu.com/equation
  pattern_tex_link = re.compile(r'\]\(\/\/zhihu\.com\/equation\?tex=')

  # fix zhihu redirection
  # [Law of large numbers](//link.zhihu.com/?target=https%3A//en.wikipedia.org/wiki/Law_of_large_numbers)
  # =>
  # [Law of large numbers](https://en.wikipedia.org/wiki/Law_of_large_numbers)
  pattern_redirect_link = re.compile(r'\]\(\/\/link\.zhihu\.com\/\?target=(.+?)\)')
  replace_redirect_link = lambda m: '](' + unquote(m.group(1)) + ')'


  for i, line in enumerate(lines):
    if not ('[' in line or '**' in line):
      continue
    # line = pattern_hyperlink.sub(r'[\1]', line)
    line = pattern_hyperlink.sub(hyperlink_replacer, line)
    line = pattern_strong.sub(replace_strong, line)
    line = pattern_redirect_link.sub(replace_redirect_link, line)
    line = pattern_tex_link.sub('](http://www.zhihu.com/equation?tex=', line)
    lines[i] = line





  with open(prefix + path, 'w', encoding='utf-8') as f2:
    f2.writelines(lines)















def save_from_author(url, folder='test', min_upvote=500, overwrite=False):
  # url = 'http://www.zhihu.com/people/nordenbox'
  author = client.Author(url)
  # 获取用户名称
  print(author.name, ' - ', author.motto)
  # 获取用户答题数
  print(author.answer_num)      # 227
  for i, answer in enumerate(author.answers):
    # if i > 20:
    #   break
    if answer.upvote_num < min_upvote:
      continue

    try:
      save_answer(answer, folder=folder, overwrite=overwrite)
    except ZhihuParseError as e:
      print(e)
    except RuntimeError as e:
      print(e, answer.question.title)
    except AttributeError as e:
      print(answer.question.title, answer_url, e)
      raise





def save_from_collections(url, limit=10):
  collection = client.Collection(url)
  print(collection.name)
  print(collection.followers_num)
  for i, answer in enumerate(collection.answers):
    # print(answer._url)
    if i >= limit:
      break

    save_answer(answer._url, folder='test')




def save_from_question(url):
  question = client.Question(url)
  print(question.title)
  # 获取排名前十的十个回答
  for answer in question.top_i_answers(10):
    if answer.upvote > 1000:
      save_answer(answer)





def save_from_topic(url, limit=200,
                    min_upvote=1000, max_upvote=100000000,
                    folder='test',
                    overwrite=True):

  if not os.path.exists(folder):
    os.makedirs(folder)

  # topic = client.Topic(url)
  topic = client.from_url(url)

  for i, answer in enumrange(topic.best_answers, limit):
    print('fetching', answer.question.title, ' - ', answer.voteup_count)

    if answer.voteup_count < min_upvote:
      break
    if answer.voteup_count > max_upvote:
      continue

    try:
      save_answer(answer, folder=folder, overwrite=overwrite)
    except RuntimeError as e:
      print(e, answer.question.title)
    except TypeError as e:
      print('question_link["href"]', e, answer.question.title)
    # except AttributeError as e:
    #   print('time to long? ', e, question_title)





















####### ##   ## ####### ######
##       ## ##  ##     ###
######    ###   ###### ##
##       ## ##  ##     ###
####### ##   ## ####### ######


def exec_save_from_collections():
  # 采铜 的收藏 我心中的知乎TOP100
  url = 'http://www.zhihu.com/collection/19845840'
  save_from_collections(url, limit=10)



def exec_save_from_authors():
  # url = 'https://www.zhihu.com/people/xbjf/'  # 玄不救非氪不改命
  # save_from_author(url, folder='authors', min_upvote=500)
  # url = 'https://www.zhihu.com/people/lu-pi-xiong/'  # 陆坏熊
  # save_from_author(url, folder='authors', min_upvote=300)
  # url = 'https://www.zhihu.com/people/zhao-hao-yang-1991'  # 赵皓阳
  # save_from_author(url, folder='authors', min_upvote=300)
  url = 'https://www.zhihu.com/people/mandelbrot-11'  # Mandelbrot
  save_from_author(url, folder='authors', min_upvote=300, overwrite=True)

# exec_save_from_authors()


def exec_save_answers():
  urls = '''
    # https://www.zhihu.com/question/40305228/answer/86179116
    # https://www.zhihu.com/question/36466762/answer/85475145
    # https://www.zhihu.com/question/33246348/answer/86919689
    # https://www.zhihu.com/question/39906815/answer/88534869

    # https://www.zhihu.com/question/40700155/answer/89002644
    # https://www.zhihu.com/question/36380091/answer/84690117
    # https://www.zhihu.com/question/33246348/answer/86919689
    # https://www.zhihu.com/question/35254746/answer/90252213
    # https://www.zhihu.com/question/23618517/answer/89823915

    https://www.zhihu.com/question/40677000/answer/87886574

    https://www.zhihu.com/question/41373242/answer/91417985
    http://www.zhihu.com/question/47275087/answer/106335325

  '''
  for url in datalines(urls):
    save_answer(url, folder='test')




def exec_save_from_question():
  urls = '''
    # graphic design
    # http://www.zhihu.com/question/19577036
    # http://www.zhihu.com/question/21578745
    # http://www.zhihu.com/question/22332149
    # http://www.zhihu.com/question/21274267
    # http://www.zhihu.com/question/22332149

    # http://www.zhihu.com/question/29594460
    # http://www.zhihu.com/question/27914845
    # http://www.zhihu.com/question/28529486
    # http://www.zhihu.com/question/20603867

    http://www.zhihu.com/question/23914832
  '''
  for url in datalines(urls):
    save_from_question(url)




def exec_save_from_topic():

  urls_str = '''
    # https://www.zhihu.com/topic/19554091 math
    # https://www.zhihu.com/topic/19556950 physics
    # https://www.zhihu.com/topic/19574449 a song of ice and fire
    # https://www.zhihu.com/topic/19556231 interactive design 1000
    # https://www.zhihu.com/topic/19556382 2d design 1000
    # https://www.zhihu.com/topic/19561709 ux design 1000
    # https://www.zhihu.com/topic/19551016 fonts 200
    # https://www.zhihu.com/topic/19553684 layout 100
    # https://www.zhihu.com/topic/19647471 style 100
    # https://www.zhihu.com/topic/19551077 history
    # https://www.zhihu.com/topic/19615699 immanuel_kant
    # https://www.zhihu.com/topic/19551864 classical music
    # https://www.zhihu.com/topic/19552330 programmer
    # https://www.zhihu.com/topic/19554298 programming
    # https://www.zhihu.com/topic/19615699 immanuel_kant



    # https://www.zhihu.com/topic/19563625 astronomy 天文
    # https://www.zhihu.com/topic/19620787 universe 天文
    # https://www.zhihu.com/topic/19569034 philosophy_of_science 科学哲学
    # https://www.zhihu.com/topic/19558740 statistics 统计
    # https://www.zhihu.com/topic/19576422 statistics 统计
    https://www.zhihu.com/topic/19552981 economics 经济
    # https://www.zhihu.com/topic/19553550 paradox 悖论
    # https://www.zhihu.com/topic/19559450 machine_learning 机器学习
    # https://www.zhihu.com/topic/19551275 artificial_intelligence 人工智能
    # https://www.zhihu.com/topic/19553534 data_mining 数据挖掘
    # https://www.zhihu.com/topic/19815465 quantitative_trading 量化交易
    # https://www.zhihu.com/topic/19571159 freelancer 自由职业
  '''

  for line in datalines(urls_str):
    url, topic_name, topic_name_cn = line.split(' ')
    puts('start parsing topic_name url')
    save_from_topic(url, limit=10, min_upvote=1000, max_upvote=5000000, folder=topic_name_cn, overwrite=False)




# exec_save_from_topic()

















####### #######  ###### #######
   ##   ##      ##         ##
   ##   ######   #####     ##
   ##   ##           ##    ##
   ##   ####### ######     ##



def test_answer_banned():
  # 为什么会出现「只有专政才能救中国」的言论？
  # 玄不救非氪不改命，东欧政治与杨幂及王晓晨研究
  # 回答建议修改：不友善内容
  # 作者修改内容通过后，回答会重新显示。如果一周内未得到有效修改，回答会自动折叠。
  url = 'https://www.zhihu.com/question/33594085/answer/74817919/'
  save_answer(url)


def test_save_answer_common():
  # 如何看待许知远在青年领袖颁奖典礼上愤怒「砸场」？
  save_answer('https://www.zhihu.com/question/30595784/answer/49194862')
  # 如何从头系统地听古典音乐？
  # save_answer('https://www.zhihu.com/question/30957313/answer/50266448')
  # 你会带哪三本书穿越回到北宋熙宁二年？
  # save_answer('https://www.zhihu.com/question/25569054/answer/31213671')



def test_save_answer_comments():
  # 如何看待许知远在青年领袖颁奖典礼上愤怒「砸场」？
  save_answer('https://www.zhihu.com/question/30595784/answer/49194862')





def test_save_answer_save_jpg_png_images():
  # 人类是否能想象出多维空间的形态？
  save_answer('https://www.zhihu.com/question/29324865/answer/45647794')


def test_save_answer_latex():
  # 大偏差技术是什么？
  save_answer('https://www.zhihu.com/question/29400357/answer/82408466')
  # save_answer('https://www.zhihu.com/question/34961425/answer/80970102')
  save_answer('https://www.zhihu.com/question/34961425/answer/74576898', overwrite=False)


def test_save_answer_drop_redirect_links():
  # 大偏差技术是什么？
  save_answer('https://www.zhihu.com/question/29400357/answer/82408466')





def test_save_anonymous():
  # 辜鸿铭的英语学习方法有效吗？为什么？
  save_answer('http://www.zhihu.com/question/20087838/answer/25073924')
  save_answer('http://www.zhihu.com/question/20087838/answer/25169641')


def test_save_should_trim_link_url_whitespace():
  # 如何追回参与高利贷而造成的损失？
  save_answer('http://www.zhihu.com/question/30787121/answer/49480841')
  # 热门的数据挖掘的论坛、社区有哪些？
  save_answer('https://www.zhihu.com/question/20142515/answer/15215875')
  # 金融专业学生应该学编程语言吗，学什么语言好呢？
  save_answer('https://www.zhihu.com/question/33554217/answer/57561928')
  # 如果太阳系是一个双恒星的星系，那地球应该是什么样的运转轨道，地球人的生活会是什么样的？
  save_answer('https://www.zhihu.com/question/38860589/answer/79205923')



def test_save_whitedot_bug():
  # QQ 的登录封面（QQ印象）是怎么设计的？
  url = 'http://www.zhihu.com/question/22497026/answer/21551914/'
  # answer = zhihu.Answer(url)
  # print(answer)
  # print(answer.content)
  save_answer(url)




def test_generate_ascii_art():
  from pyfiglet import Figlet

  print(Figlet(font='space_op').renderText('flask'))





def test_html2text():
  import html2text
  h = html2text.HTML2Text()
  # h.ignore_links = True
  print(h.handle("<p>Hello, <a href='http://earth.google.com/'>world</a>!"))

  import html2text
  h2t = html2text.HTML2Text()
  h2t.body_width = 0

  html = '11111111<br>222222<br><br><br><br>3333333'
  a = h2t.handle(html)
  puts('a=')
  b = zhihu_content_html2md(html)
  puts('b=')
  # print(html.split('\n'))
  # print('\n'.join(p for p in html.split('\n')))
  # print('\n'.join(p.rstrip() for p in html.split('\n')))
  # print(zhihu_content_html2md(html))




def done_test_fix_img():
  import html2text
  h2t = html2text.HTML2Text()
  h2t.body_width = 0
  # 'http://zhuanlan.zhihu.com/xiepanda'
  # url = 'http://www.zhihu.com/question/30595784/answer/49194862'
  # url = 'http://www.zhihu.com/question/19622414/answer/19798844'
  # url = 'http://www.zhihu.com/question/24413365/answer/27857112'
  url = 'http://www.zhihu.com/question/23039503/answer/48635152'
  answer = zhihu.Answer(url)
  content = answer.content
  answer_body = h2t.handle(content)
  puts('answer content= answer_body=')






def test_md_prettify():
  path = '苏州？ - 王維鈞的回答.md'
  markdown_prettify(path, )




def test_md_line_replace():
  text = '感谢 [ @Jim Liu ](http://www.zhihu.com/744db) 乱入的 ** 湖北白河村 ** 与 ** 邯郸玉佛寺 ** ） **王維鈞（作者）** 回复 **Jade Shan**: 他作了一首诗：“床前明月光， ** 脱光光。'
  pattern_hyperlink = re.compile(r'\[ (.+?) \](?=\(.+?\))')
  pattern_strong = re.compile(r'\*\* (.+?) \*\*')
  replace = lambda m: '** 回复 **' if m.group(1) == '回复' else '**'+m.group(1)+'**'
  text2 = pattern_hyperlink.sub(r'[\1]', text)
  text3 = pattern_strong.sub(replace, text2)
  puts()
  print(text3)
  # print(text3)







def test_fetch_images_for_markdown_file():
  # QQ 的登录封面（QQ印象）是怎么设计的？
  url = 'http://www.zhihu.com/question/22497026/answer/21551914/'
  save_answer(url)
  markdown_file = '/Users/probe/git/zhihumark/test/QQ 的登录封面（QQ印象）是怎么设计的？ - 傅仲的回答.md'
  fetch_images_for_markdown_file(markdown_file)

  # path = '/Users/probe/git/zhihumark/test'
  # # i = 0
  # for markdown_file in all_files(path, patterns='*.md'):
  #   # i += 1
  #   # if i > 5:
  #   #   break

  #   print(markdown_file)
  #   fetch_images_for_markdown_file(markdown_file)






def test_time():
  print(time.strftime('%Y-%m-%d'))


def test_new_zhihu():
  url = 'https://www.zhihu.com/question/30957313/answer/50266448'
  answer = client.answer(url) | puts()
  answer.author | puts()
  answer.collect_num | puts()
  answer.upvote_num | puts()
  answer.content | puts()
  for c in list(answer.comments):
    (c.author.name, c.content) | puts()




def test_download():

  # save_author('http://www.zhihu.com/people/nordenbox')
  urls = '''
    # http://www.zhihu.com/people/leng-zhe
    # http://www.zhihu.com/people/ji-xuan-yi-9
    # http://www.zhihu.com/people/Ivony
    # http://www.zhihu.com/people/BlackCloak

    # http://www.zhihu.com/people/hecaitou
    # http://www.zhihu.com/people/ma-bo-yong

    # http://www.zhihu.com/people/hutianyi
    # http://www.zhihu.com/people/lawrencelry
    # http://www.zhihu.com/people/Metaphox

    # http://www.zhihu.com/people/calon
    # http://www.zhihu.com/people/yolfilm
    # http://www.zhihu.com/people/superwyh
    # http://www.zhihu.com/people/cai-tong
    # http://www.zhihu.com/people/xiepanda




    # http://www.zhihu.com/people/cogito
    # http://www.zhihu.com/people/talich
    # http://www.zhihu.com/people/commando
    # http://www.zhihu.com/people/fu-er

    # http://www.zhihu.com/people/tassandar
    # http://www.zhihu.com/people/fei-niao-bing-he
    # http://www.zhihu.com/people/zhou-xiao-nong
    # http://www.zhihu.com/people/wang-lu-43-95
    # http://www.zhihu.com/people/yinshoufu
    # http://www.zhihu.com/people/tangsyau
    # http://www.zhihu.com/people/lianghai
    # http://www.zhihu.com/people/zhang-jia-wei
    # http://www.zhihu.com/people/bo-cai-28-7

    # all done
  '''

  urls = '''
    http://www.zhihu.com/people/sa-miu-47-86
    http://www.zhihu.com/people/xubowen
  '''


  for url in datalines(urls):
    save_from_author(url, folder='authors_explore', min_upvote=1000)



def test_comment():
  import html2text
  h2t = html2text.HTML2Text()
  h2t.body_width = 0

  url = 'http://www.zhihu.com/question/30557155/answer/49730622'
  url = 'http://www.zhihu.com/question/27794207/answer/46866751'

  answer = zhihu.Answer(url)
  # content = answer.content
  # puts(content)
  aid = answer.comment_list_id
  puts(aid)
  for comment in answer.comments:
    print(comment)

  puts('valuable_comments-------')
  for comment in answer.valuable_comments():
    print(comment)

  # answer_body = h2t.handle(content)
  # puts('answer answer_body=')





def exec_newspaper():
  print(11)




def save_comments():

  pass
      # 2016.01.18 Probe add

      @property
      @check_soup('_comment_list_id')
      def comment_list_id(self):
          """返回 aid 用于拼接 url get 该回答的评论
          <div tabindex="-1" class="zm-item-answer" itemscope="" itemtype="http://schema.org/Answer" data-aid="14852408" data-atoken="48635152" data-collapsed="0" data-created="1432285826" data-deleted="0" data-helpful="1" data-isowner="0" data-score="34.1227812032">
          """
          div = self.soup.find('div', class_='zm-item-answer')
          return div['data-aid']

      @property
      def comments_quick(self):
          url = 'http://www.zhihu.com/node/AnswerCommentBoxV2?params=%7B%22answer_id%22%3A%22{}%22%2C%22load_all%22%3Atrue%7D'.format(self.comment_list_id)
          # print(url)
          r = self._session.get(url)
          soup = BeautifulSoup(r.content)
          comments = []
          for div in soup.find_all('div', class_='zm-item-comment'):
              # print(div)
              # print(div.text)
              raw_content = div
              comment_id = div["data-id"]
              # author = div.find('a', class_='zm-item-link-avatar')['title']

              likes = int(div.find('span', class_='like-num').find('em').text)
              content = div.find('div', class_='zm-comment-content').prettify().strip()
              author_text = div.find('div', class_='zm-comment-hd').text.strip().replace('\n', ' ')
              # print(author_text)
              if ' 回复 ' in author_text:
                  author, reply_to = author_text.split(' 回复 ')
              else:
                  author, reply_to = author_text, None

              # author = reply_ids[0]
              # reply_to = None if len(reply_ids) == 1 else reply_ids[1]
              comment = CommentQuick(raw_content, comment_id, author, likes, content, reply_to)

              comments.append(comment)
          return comments

      @property
      def conversations(self):
          '''会话, 评论区的所有评论的分组
          规则:
          0. comment 分为直接评论和回复别人两种
          1. 从第一个评论开始, 将每一个评论归入合适的分组, 否则建新分组
          2. 直接评论视为开启新的会话
          3. B回复A, 放入B回复的A的评论的会话,
              如果A已经出现在n个会话里, 寻找A之前是否回复过B,
                  A回复过B: 放在这一组会话里,
                  A没有回复过B: 放在A最晚说话的那一条评论的会话里 second_choice

          '''
          result = []
          for comment in self.comments_quick:
              if not comment.reply_to:  # 直接评论, 开启新的会话
                  result.append([comment])
              else:                     # 回复别人
                  second_choice = None  # A最晚说话的那一条评论的会话
                  for conversation in reversed(result):  # 反着查找, 获取时间最近的匹配
                      if comment.reply_to in [c.author for c in conversation]:
                          second_choice = second_choice or conversation
                          if comment.author in [c.reply_to for c in conversation]:  # B回复A之前, A也回复过B
                              conversation.append(comment)
                              break
                  else:  # B回复A, 但是A没有回复过B, 或者A被删了评论
                      if second_choice:  # A没有回复过B 放在A最晚说话的那一条评论的会话里
                          second_choice.append(comment)
                      else:  # A被删了评论, 只好加入新的会话分组
                          result.append([comment])

          return result

      def valuable_conversations(self, limit=10):
          '''
          limit: 有效的会话组里的likes总和最大的 n 个对话
          '''
          # result = []

          # for conversation in self.conversations:
          #     if sum(comment.likes for comment in conversation) >= limit:
          #         result.append(conversation)
          # return result

          sum_likes = lambda conversation: sum(comment.likes for comment in conversation)
          return sorted(self.conversations, key=sum_likes, reverse=True)[:limit]

      # def valuable_comments(self, min_likes=5):
      #     result = []
      #     reply_to_authors = set()
      #     comments = self.comments
      #     for comment in reversed(comments):
      #         if comment.likes < min_likes and comment.author not in reply_to_authors:
      #             continue
      #         if comment.reply_to:
      #             reply_to_authors.add(comment.reply_to)
      #         result.append(comment)
      #     return list(reversed(result))




  class CommentQuick():
      ''' 更快速的评论对象
      知乎于2016年1月修改评论显示模式(加了分页and查看上下文对话)
      此为原始的评论获取方法
      使用 url = 'http://www.zhihu.com/node/AnswerCommentBoxV2?params=%7B%22answer_id%22%3A%22{}%22%2C%22load_all%22%3Atrue%7D'.format(self.comment_list_id)
      拼接获取评论

      '''
      def __init__(self, raw_content, comment_id, author, likes, content, reply_to):
          self.raw_content = raw_content
          self.comment_id = comment_id
          self.author = author
          self.likes = likes
          self.content = content
          self.reply_to = reply_to

      def __str__(self):
          return '<Comment id={0.comment_id}> author: {0.author} reply_to: {0.reply_to} likes={0.likes} {0.content}'.format(self)
