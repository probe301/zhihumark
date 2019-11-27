
import time
import os
import shutil
import re
import random
from datetime import datetime

from fetcher import Fetcher
from collections import OrderedDict as odict
from collections import Counter
from pprint import pprint
import tools

log = tools.create_logger(__file__)
log_error = tools.create_logger(__file__ + '.error')

from task import Task
from fetcher import UrlType
from fetcher import parse_type
from fetcher import purge_url
from tools import create_logger
from tools import time_to_str
from tools import duration_from_humanize
from tools import time_now
from tools import time_now_str
from tools import time_from_str
from tools import time_to_humanize
from tools import remove_invalid_char

from fetcher import Fetcher
from page import Page
# from werkzeug.contrib.atom import AtomFeed
from feedgen.feed import FeedGenerator



class Watcher:
  '''
  Watcher 为目录下具有 .config.yaml 的目录, 负责调度和执行抓取

  .config.yaml 只读, 指定全局设置, 和 lister
  .tasks.yaml 系统自动覆写, 记录已经抓取过的页面

  当创建 Watcher() 时:
    加载该 folder 下的 .tasks.yaml, 里面是已记录的 lister_tasks 和 page_tasks
    加载该 folder 下的 .config.yaml, 里面可能有新建的 lister_tasks
    输出一个报告

  当 watcher.watch() 时:
    首先运行 lister_task 里的任务, 检测这些列表页是否新增了页面
      如果检测到新增页面, 创建新的 page_task 
      如果检测到的是本地 page_task 中已存在的页面, 按照预定的抓取时间处理
    然后运行 page_task 里的任务, 挨个抓取

    每完成一个 batch (比如 10 个更新) 之后, 交给 git 提交记录
    并输出一个报告
  '''
  def __init__(self, watcher_path):
    '''
    1 加载该 folder 下的 .tasks.yaml, 里面是已记录的 lister_tasks 和 page_tasks
    2 加载该 folder 下的 .config.yaml, 里面可能有新建的 lister_tasks
 
    .tasks.yaml 中需要记录 url, tip, date x4, version
    而 lister_limit, page_max_cycle, lister_min_cycle ... 等记录在 .config.yaml 中

    '''
    self.watcher_path = watcher_path
    self.folder = os.path.basename(watcher_path)
    self.watcher_option = tools.yaml_load(self.watcher_path + '/.config.yaml')

    self.task_dict = {}  # load_local_tasks task_dict 预备以 url 作为 key
    # 1 从 task.json 中载入已有 task
    # 2 对于 page task, 加入该 watcher 的 env_option
    # 3 对于 lister task, 加入该 watcher 的 env_option, 以及 listers 里特定的属性
    local_tasks = tools.yaml_load(os.path.join(self.watcher_path, '.tasks.yaml'))
    env_task_option = self.watcher_option.get('task_option')
    for task in local_tasks:
      self.task_dict[task['url']] = Task.create(task, env_task_option)

    # 更新 lister_option 中的 task, 用户可能修改了单独某个 lister 的 option
    for task in self.watcher_option.get('lister_option', []):
      url = task['url']
      tip = task['tip']
      # custom_option = config.yaml 的全局 task 设置 + lister 自定义设置
      custom_option = tools.dict_merge(env_task_option, task.get('option', {}))
      if url in self.task_dict:
        self.task_dict[url].update_option(custom_option)
      else:
        self.task_dict[url] = Task.create({'url': url, 'tip': tip}, custom_option)

    # TODO 更新 page_option 中的 task, 用户可能修改了单独某个 page 的 option
    # for task in self.watcher_option.get('page_option', []):
    #   custom_option = tools.dict_merge(env_task_option, task.get('option', {}))
    #   self.task_dict[task['url']] = Task.create(task, custom_option) 



  # @classmethod TODO
  # def create(cls, path):
  #   if os.path.exists(path):
  #     raise FileExistsError(f'create_watcher `{path}` exists')
        # # 项目默认设置
        # WATCHER_DEFAULT_OPTION = odict(
        #   git_commit_path='none',   # 使用 git 提交记录, 可选上一层目录 '..', 当前目录 '.', 或默认 none
        #   git_commit_batch=10,      # 每 10 个页面执行一个提交
        #   save_attachments=False,
        #   enabled=True,
        #   weight=0.5,               # 默认权重, 影响抓取优先级
        #   lister_max_cycle='30days' # 对 Watcher 目录里的所有 lister 起效, 会被具体设置覆盖
        #   lister_min_cycle='12hours'
        #   lister_limit=200,         # 从 lister 中返回的最大条目
        #   page_max_cycle='180days', # 对 Watcher 目录里的所有 page 起效
        #   page_min_cycle='45days',
        # )

  #   return 

  @classmethod
  def open(cls, path):
    if not os.path.exists(path):
      raise FileNotFoundError(f'open_watcher `{path}` not exists')
    if not os.path.exists(path + '/.config.yaml'):
      raise FileNotFoundError(f'open_watcher `{path}/.config.yaml` not exists')
    if not os.path.exists(path + '/.tasks.yaml'):
      tools.json_save([], path + '/.tasks.yaml')
    return cls(path)

  def __str__(self):
    s = '''<Watcher #{}>
      from `{}`, {} tasks'''
    return s.format(id(self), self.watcher_path, self.tasks_count)


  @property
  def git_project_path(self):
    section = self.watcher_option.get('version_control_option')
    if section:
      return os.path.join(self.watcher_path, section.get('git_commit_path', '.'))
    else:
      return ''
  @property
  def git_commit_batch(self):
    section = self.watcher_option.get('version_control_option')
    if section:
      return section.get('git_commit_batch', 3)
    else:
      return 3


  @property
  def listers(self):
    section = self.watcher_option.get('lister_option', [])
    return [l['url'] for l in section]

  def add_task(self, task_desc):
    ''' 添加一个 Task, 以 url 判断是否为已存在的 Task
        返回 task 属于四种情况的数量
          new        当前未知的新任务, 
          seen       当前任务列表中已存在的任务 (url 已知)
          prepare    任务已到抓取时间, 等待抓取
          wait       任务不到抓取时间
    '''
    env_task_option = self.watcher_option.get('task_option')
    url = task_desc['url']
    seen_task = self.task_dict.get(url)
    if seen_task:
      if seen_task.next_watch_time <= time_now(): return "seen+prepare"
      else: return "seen+wait"
    else:
      new_task = Task.create(task_desc, env_task_option)
      self.task_dict[url] = new_task
      return "new+prepare"


  def add_tasks(self, tasks_desc):
    ''' 添加任务列表, 并输出报告
        在 watcher 加载 config yaml 时调用, 以及 lister 检测到 new page 时调用
        输出报告 task 属于四种情况的数量
          new        当前未知的新任务, 
          seen       当前任务列表中已存在的任务 (url 已知)
          prepare    任务已到抓取时间, 等待抓取
          wait       任务不到抓取时间
    '''
    results = []
    for task_desc in tasks_desc:
      result = self.add_task(task_desc)
      results.append(result)
    log(f'watcher add {len(tasks_desc)} tasks: {dict(Counter(results))}')
    return Counter(results)

  @property
  def tasks_count(self): return len(self.task_dict.keys())

  def save_tasks_yaml(self):
    ''' 存盘 .tasks.yaml
        按照添加顺序存放
    '''
    tasks = sorted(self.task_dict.values(), key=lambda t: t.task_add_time)
    temp = ''
    for task in tasks:
      temp += task.to_yaml_text()
      temp += '\n'
    tools.save_txt(path=self.watcher_path + '/.tasks.yaml', data=temp)

  def run(self):
    ''' 爬取页面, 
        首先列出所有的NewPost任务, 都抓取一遍
        然后列出普通页面任务, 都抓取一遍
    '''
    lister_tasks_queue = []
    for task in self.task_dict.values():
      if task.should_fetch and task.is_lister_type:
        lister_tasks_queue.append(task)
    lister_tasks_queue.sort(key=lambda x: -x.priority)
    log(f'watching listers... should fetch {len(lister_tasks_queue)} lister tasks\n')
    for i, task in enumerate(lister_tasks_queue, 1):
      # log('Watcher.watch lister task.run: {}'.format(task))
      new_tasks_json = task.run()
      counter = self.add_tasks(new_tasks_json)
      is_modified = counter["new+prepare"] > 0
      task.schedule(is_modified=is_modified) # is_modified = add_tasks 时出现了新的 task
      log(f'lister task done ({i}/{len(lister_tasks_queue)}): \n{task}\n\n')
      self.save_tasks_yaml()
      yield {'commit_log': f'check lister {i}/{len(lister_tasks_queue)}, {task.brief_tip}'}
      # self.remember(commit_log='checked lister {}'.format(i), watcher_path=self.watcher_path)
      tools.time_random_sleep(5, 10)


    page_tasks_queue = []
    for task in self.task_dict.values():
      if task.should_fetch and task.is_page_type:
        page_tasks_queue.append(task)
    page_tasks_queue.sort(key=lambda x: -x.priority)
    log(f'watching pages... should fetch {len(page_tasks_queue)} page tasks\n')
    if len(page_tasks_queue) == 0: return


    
    for tasks_batch in tools.windows(enumerate(page_tasks_queue, 1), self.git_commit_batch, yield_tail=True):
      # log('Watcher.watch page task: {}'.format(task))

      for i, task in tasks_batch:
        page_json = task.run()
        page_json['metadata']['folder'] = self.watcher_path
        page_json['metadata']['version'] = task.version + 1
        page = Page.create(page_json)
        page.write()
        # if task.last_page:
        #   is_modified = page.is_changed(self.last_page)
        # else:
        #   is_modified = True
        # self.last_page = page
        task.schedule(is_modified=is_modified)  # is_modified = 跟上次存储的页面有区别
        log(f'page task done ({i}/{len(page_tasks_queue)}): \n{task}\n\n')

      self.save_tasks_yaml()
      commit_tasks_log = ','.join(task.brief_tip for i, task in tasks_batch)
      yield {'commit_log': f'save {len(tasks_batch)} pages, {commit_tasks_log}'}
      # self.remember(commit_log='save pages {}'.format(i))

      tools.time_random_sleep(5, 10)


  def watch_once(self):
    log(f'\n  ↓ start watch_once for\n  {self}')
    for commit_log in self.run():
      self.remember(commit_log)
    log(f'  ↑ start watch_once done\n')


  def remember(self, commit_log, verbose=False):
    ''' 如果使用 git, 将 watcher 抓取到的内容存储到 project git 仓库 '''
    if isinstance(commit_log, dict):
      commit_log = commit_log.get('commit_log', 'missing commit log')
    if self.git_project_path:
      cmd = f'cd "{self.git_project_path}" && git add . && git commit -m "{commit_log}"'
      # log(cmd)
      tools.run_command(cmd, verbose=verbose)
      log(f'git committed: "{commit_log}"\n')
    else:
      log(commit_log)


  def report(self):
    ''' 输出 Watcher folder 的摘要 '''
    log(f'report {self} \n---------------------')
    folder = self.folder
    folder_md5 = tools.md5(self.folder, 10)
    all_pages = tools.all_files(self.watcher_path, patterns='*.md', single_level=True)
    count = len(list(all_pages))
    log(f'    Watcher: "{folder}" ({folder_md5}) {count} pages)')
    
    if self.git_project_path:
      output = tools.run_command(f'cd "{self.git_project_path}" && git log --oneline -n 5')
      log('git log: ')
      for line in output.splitlines():
        log(f'    {line.strip()}')
    log(f'---------------------')



# =========================================================
# =================== end of class Watcher ================
# =========================================================



