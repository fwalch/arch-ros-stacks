#!/usr/bin/env python2

from __future__ import print_function

import catkin_pkg.package
from optparse import OptionParser
import os
import os.path
import urllib2
import urlparse
import yaml
import re
from collections import OrderedDict
from termcolor import colored, cprint

class PackageBase(object):

  def __init__(self, distro, repository_url, name, version, version_patch):
    self.packages = []
    self.distro = distro
    self.repository_url = repository_url
    package = self._parse_package_file(
      self._get_package_xml_url(repository_url, name, version))
    self.name = package.name
    self.version = package.version
    self.version_patch = version_patch
    self.licenses = package.licenses
    self.run_dependencies = list(OrderedDict.fromkeys([dependency.name for dependency in package.run_depends]))
    self.build_dependencies = list(OrderedDict.fromkeys([dependency.name for dependency in package.build_depends + package.buildtool_depends]))
    # Build dependencies already added:
    if 'git' in self.build_dependencies: self.build_dependencies.remove('git')
    if 'cmake' in self.build_dependencies: self.build_dependencies.remove('cmake')

    # Remove HTML tags from description
    self.description = re.sub('<[^<]+?>', '', package.description)
    # Put it on one line to motivate packagers to make shorter descriptions
    self.description = re.sub('\n', ' ', self.description)
    # Convert tabs to spaces
    self.description = re.sub('\t', ' ', self.description)
    # Multiple consecutive spaces turned into one
    self.description = re.sub('([ ]+)', ' ', self.description)
    # Only take the first sentence (keep short description)
    self.description = self.description.split(".")[0] + "."
    # Handle quotes
    self.description = self.description.replace('"', '').replace('`', '').replace('&quot;', '').replace('\'','')

  def _parse_package_file(self, url):
    """
    Parses the package.xml file specified by `url`.

    Arguments:
    - `url`: Valid URL pointing to a package.xml file.
    """
    return catkin_pkg.package.parse_package_string(
      urllib2.urlopen(url).read())

  def _fix_dependencies(self, rosdep_urls, build_dep, run_dep):
    # Fix usual non-ROS dependencies:
    #  - load replacement dictionary: these are found in rosdep yaml files. We
    #                                 just need to download and merge these files
    #                                 in a dictionary.
    dependency_map = self._get_rosdep_dictionary(rosdep_urls)

    def _fix_dependencies_with_map(dependencies):
      fixed_dependencies = set()
      #  - replace in other_dependencies
      for index, dep in enumerate(dependencies):
        if (dep in dependency_map):
          # The map may replace one package by multiple ones, or even by none
          for package in dependency_map[dep]:
            fixed_dependencies.add(package)
        else:
          fixed_dependencies.add(dep)

      # Fix some possibly missing Python 2 package conflicts
      fixed_dependencies = [self._ensure_python2_dependency(dependency)
                            for dependency in fixed_dependencies]
      return fixed_dependencies

    fixed_build_dep = _fix_dependencies_with_map(build_dep)
    fixed_run_dep = _fix_dependencies_with_map(run_dep)

    return fixed_build_dep, fixed_run_dep

  def _get_ros_dependencies(self):
    """
    Returns (build_dependencies, run_dependencies)
    """
    known_packages = self.distro.package_names(expand_metapackages=True)
    build_dep = list(set([self._rosify_package_name('ros-%s-' % self.distro.name + dependency)
                           for dependency in self.build_dependencies if dependency in known_packages]))
    run_dep = list(set([self._rosify_package_name('ros-%s-' % self.distro.name + dependency)
                           for dependency in self.run_dependencies if dependency in known_packages]))
    return build_dep, run_dep

  def _get_non_ros_dependencies(self, rosdep_urls=[]):
    """
    Returns (build_dependencies, run_dependencies)
    """
    known_packages = self.distro.package_names(expand_metapackages=True)

    other_build_dep = list(set([dependency for dependency in self.build_dependencies
                               if dependency not in known_packages]))
    other_run_dep = list(set([dependency for dependency in self.run_dependencies
                               if dependency not in known_packages]))
    return self._fix_dependencies(rosdep_urls, other_build_dep, other_run_dep)

  def _rosify_package_name(self, name):
    return name.replace('_', '-')

  def _ensure_python2_dependency(self, dependency):
    return dependency.replace('python-', 'python2-')

  def _get_package_xml_url(self, url, name, version):
    if url.find('github'):
      if self.distro.name != "fuerte":
        return github_raw_url(url, 'package.xml', 'release/%s/%s' % (self.distro.name, name))
      else: # fuerte-specific
        return github_raw_url(url, 'package.xml', 'release/%s/%s' % (name, version))
    else:
      raise Exception('Unable to generate url for package.xml')

  def _get_rosdep_dictionary(self, rosdep_urls):
    dependency_map = {}
    for rosdep_url in rosdep_urls:
      stream = urllib2.urlopen(rosdep_url)
      rosdep_file = yaml.load(stream)
      for package_name, distrib in rosdep_file.items():
        if 'arch' in distrib:
          dependency_map[package_name] = distrib["arch"]
    return dependency_map

  def generate(self, exclude_dependencies=[]):
    raise Exception('`generate` not implemented.')

  def is_same_version(self, pkgbuild_file):
    """
    Checks whether a currently installed PKGBUILD contains the same version.
    """
    if os.path.isfile(pkgbuild_file):
      f = open(pkgbuild_file, "r")
      content = f.read()
      pattern_pkgver = re.compile(r"pkgver='([0-9\.]*)'")
      pattern_pkgver_patch = re.compile(r"_pkgver_patch=([0-9]*)")
      match_pkgver = re.search(pattern_pkgver, content)
      match_pkgver_patch = re.search(pattern_pkgver_patch, content)
      if match_pkgver and match_pkgver_patch:
        return (match_pkgver.group(1) == self.version
                and match_pkgver_patch.group(1) == self.version_patch)
      else:
        return False
    else:
      return False


class Package(PackageBase):
  BUILD_TEMPLATE = """
pkgdesc="ROS - %(description)s"
url='http://www.ros.org/'

pkgname='ros-%(distro)s-%(arch_package_name)s'
pkgver='%(package_version)s'
_pkgver_patch=%(package_version_patch)s
arch=('i686' 'x86_64')
pkgrel=1
license=('%(license)s')

ros_makedepends=(%(ros_build_dependencies)s)
makedepends=('cmake' 'git' 'ros-build-tools'
  ${ros_makedepends[@]}
  %(other_build_dependencies)s)

ros_depends=(%(ros_run_dependencies)s)
depends=(${ros_depends[@]}
  %(other_run_dependencies)s)

_tag=release/%(distro)s/%(package_name)s/${pkgver}-${_pkgver_patch}
_dir=%(package_name)s
source=("${_dir}"::"git+%(package_url)s"#tag=${_tag})
md5sums=('SKIP')

build() {
  # Use ROS environment variables
  /usr/share/ros-build-tools/clear-ros-env.sh
  [ -f /opt/ros/%(distro)s/setup.bash ] && source /opt/ros/%(distro)s/setup.bash

  # Create build directory
  [ -d ${srcdir}/build ] || mkdir ${srcdir}/build
  cd ${srcdir}/build

  # Fix Python2/Python3 conflicts
  /usr/share/ros-build-tools/fix-python-scripts.sh ${srcdir}/${_dir}

  # Build project
  cmake ${srcdir}/${_dir} \\
        -DCMAKE_BUILD_TYPE=Release \\
        -DCATKIN_BUILD_BINARY_PACKAGE=ON \\
        -DCMAKE_INSTALL_PREFIX=/opt/ros/%(distro)s \\
        -DPYTHON_EXECUTABLE=/usr/bin/python2 \\
        -DPYTHON_INCLUDE_DIR=/usr/include/python2.7 \\
        -DPYTHON_LIBRARY=/usr/lib/libpython2.7.so \\
        -DSETUPTOOLS_DEB_LAYOUT=OFF
  make
}

package() {
  cd "${srcdir}/build"
  make DESTDIR="${pkgdir}/" install
}
"""

  def generate(self, exclude_dependencies=[], rosdep_urls=[]):
    raw_build_dep, raw_run_dep = self._get_ros_dependencies()
    ros_build_dep = [dependency for dependency in raw_build_dep
                     if dependency not in exclude_dependencies]
    ros_run_dep = [dependency for dependency in raw_run_dep
                   if dependency not in exclude_dependencies]

    other_raw_build_dep, other_raw_run_dep = self._get_non_ros_dependencies(rosdep_urls)
    other_build_dep = [dependency for dependency in other_raw_build_dep
                     if dependency not in exclude_dependencies]
    other_run_dep = [dependency for dependency in other_raw_run_dep
                   if dependency not in exclude_dependencies]

    pkgbuild = self.BUILD_TEMPLATE % {
      'distro': self.distro.name,
      'arch_package_name': self._rosify_package_name(self.name),
      'package_name': self.name,
      'package_version': self.version,
      'package_version_patch': self.version_patch,
      'package_url': self.repository_url,
      'license': ', '.join(self.licenses),
      'description': self.description,
      'ros_build_dependencies': '\n  '.join(ros_build_dep),
      'ros_run_dependencies': '\n  '.join(ros_run_dep),
      'other_build_dependencies': '\n  '.join(other_build_dep),
      'other_run_dependencies': '\n  '.join(other_run_dep)
      }

    # Post-processing:
    # Remove useless carriage return
    pkgbuild = re.sub('\\n  \)', ')', pkgbuild)
    return pkgbuild


class MetaPackage(PackageBase):
  BUILD_TEMPLATE = """
pkgdesc="ROS - %(description)s"
url='http://www.ros.org/'

pkgname='ros-%(distro)s-%(arch_package_name)s'
pkgver='%(package_version)s'
arch=('i686' 'x86_64')
pkgrel=1
license=('%(license)s')

ros_makedepends=(%(ros_build_dependencies)s)
makedepends=('cmake' 'git' 'ros-build-tools'
  ${ros_makedepends[@]}
  %(other_build_dependencies)s)

ros_depends=(%(ros_run_dependencies)s)
depends=(${ros_depends[@]}
  %(other_run_dependencies)s)

source=()
md5sums=()
"""

  def __init__(self, distro, repository_url, name, version, version_patch):
    super(MetaPackage, self).__init__(distro, repository_url, name, version, version_patch)
    self.packages = [Package(distro, repository_url, child_name, version, version_patch)
                     for child_name in distro.meta_package_package_names(name)]

  def generate(self, exclude_dependencies=[], rosdep_urls=[]):
    raw_build_dep, raw_run_dep = self._get_ros_dependencies()
    ros_build_dep = [dependency for dependency in raw_build_dep
                     if dependency not in exclude_dependencies]
    ros_run_dep = [dependency for dependency in raw_run_dep
                   if dependency not in exclude_dependencies]

    other_raw_build_dep, other_raw_run_dep = self._get_non_ros_dependencies(rosdep_urls)
    other_build_dep = [dependency for dependency in other_raw_build_dep
                     if dependency not in exclude_dependencies]
    other_run_dep = [dependency for dependency in other_raw_run_dep
                   if dependency not in exclude_dependencies]
    pkgbuild = self.BUILD_TEMPLATE % {
      'distro': self.distro.name,
      'arch_package_name': self._rosify_package_name(self.name),
      'package_name': self.name,
      'package_version': self.version,
      'package_version_patch': self.version_patch,
      'license': ', '.join(self.licenses),
      'description': self.description,
      'ros_build_dependencies': '\n  '.join(ros_build_dep),
      'ros_run_dependencies': '\n  '.join(ros_run_dep),
      'other_build_dependencies': '\n  '.join(other_build_dep),
      'other_run_dependencies': '\n  '.join(other_run_dep)
      }

    # Post-processing:
    # Remove useless carriage return
    pkgbuild = re.sub('\${ros_depends\[@\]}\\n  \)',
                      '${ros_depends[@]})', pkgbuild)
    return pkgbuild


class DistroDescription(object):

  def __init__(self, name, url):
    stream = urllib2.urlopen(url)
    self.name = name
    self._distro = yaml.load(stream)
    self._package_cache = {}
    if self.name == "fuerte":
      if self.name != self._distro['release-name']:
        raise Exception('ROS distro names do not match (%s != %s)' % (self.name, self._distro['release-name']))
    # process "metapackages"
    if 'metapackages' in self._distro['repositories'].keys():
      metapackages = self._distro['repositories']['metapackages']['release']
      for meta in metapackages['packages']:
        self._distro['repositories'][meta] = {}
        self._distro['repositories'][meta]['release'] = {}
        self._distro['repositories'][meta]['release']['url'] = metapackages['url']
        self._distro['repositories'][meta]['release']['version'] = metapackages['version']
    del self._distro['repositories']['metapackages']


  def package_names(self, expand_metapackages=False):
    packages = [name for name in self._distro['repositories'].keys()]
    if expand_metapackages:
      return sum([([name] + self.meta_package_package_names(name)) if self._is_meta_package(name) else [name]
                  for name in packages],
                 [])
    else:
      return packages

  def is_package(self, name):
    return self._get_package_data(name) != None

  def package(self, name):
    package_data = self._get_package_data(name)
    if not package_data:
      raise Exception('Unable to find package `%s`' % name)
    if self._package_cache.get(name):
      return self._package_cache[name]
    url = package_data['url']
    version = package_data['version'].split('-')[0]
    version_patch = package_data['version'].split('-')[1]
    # WARNING: some metapackages embed a package with the same name. In this case,
    #          we treat the package as a normal package.
    if self._is_meta_package(name) and (not name in self._distro['repositories'][name]['release']['packages']):
      package = MetaPackage(self, url, name, version, version_patch)
    else:
      package = Package(self, url, name, version, version_patch)
    self._package_cache[name] = package
    return package

  def meta_package_package_names(self, name):
    return self._distro['repositories'][name]['release']['packages']

  def _is_meta_package(self, name):
    if self._distro['repositories'].get(name) != None:
      if self._distro['repositories'][name].get('release') != None:
        return (self._distro['repositories'][name]['release'].get('packages') != None)

  def _get_package_data(self, name):
    """Searches for `name` in all known packages and metapackages."""
    if self._distro['repositories'].get(name):
      return self._distro['repositories'][name]['release']
    else:
      for package in self.package_names():
        if (self._is_meta_package(package)
            and name in self._distro['repositories'][package]['release']['packages']):
          return self._distro['repositories'][package]['release']


def list_packages(distro_description):
  print(*distro_description.package_names(), sep='\n')


### From http://code.activestate.com/recipes/577058/ (r2)
def query_yes_no(question, default="yes"):
  """Ask a yes/no question via raw_input() and return their answer.

  "question" is a string that is presented to the user.
  "default" is the presumed answer if the user just hits <Enter>.
      It must be "yes" (the default), "no" or None (meaning
      an answer is required of the user).

  The "answer" return value is one of "yes" or "no".
  """
  valid = {"yes":"yes",   "y":"yes",  "ye":"yes",
           "no":"no",     "n":"no"}
  if default == None:
      prompt = " [y/n] "
  elif default == "yes":
      prompt = " [Y/n] "
  elif default == "no":
      prompt = " [y/N] "
  else:
      raise ValueError("invalid default answer: '%s'" % default)
  while True:
      print(question + prompt)
      choice = raw_input().lower()
      if default is not None and choice == '':
          return default
      elif choice in valid.keys():
          return valid[choice]
      else:
          print("Please respond with 'yes' or 'no' (or 'y' or 'n').")


def github_raw_url(repo_url, path, commitish):
  """
  Returns the URL of the file blob corresponding to `path` in the
  github repository `repo_url` in branch, commit or tag `commitish`.
  """
  url = urlparse.urlsplit(repo_url)
  return 'https://raw.%(host)s%(repo_path)s/%(branch)s/%(path)s' % {
    'host': url.hostname,
    'repo_path': url.path.replace('.git', ''),
    'branch': commitish,
    'path': path
    }


def generate_pkgbuild(distro, package, directory, force=False,
                      no_overwrite=False, recursive=False, update=False,
                      exclude_dependencies=[], rosdep_urls=[], generated=None):
  if generated is None:
    generated = []
  elif package.name in generated:
    return
  generated.append(package.name)
  if package.packages:
    for child_package in package.packages:
      generate_pkgbuild(distro, child_package, directory,
                        force=force, exclude_dependencies=exclude_dependencies,
                        no_overwrite=no_overwrite, recursive=recursive,
                        update=update, rosdep_urls=rosdep_urls, generated=generated)
  if recursive:
    for dependency in package.run_dependencies + package.build_dependencies:
      if distro.is_package(dependency):
        generate_pkgbuild(distro, distro.package(dependency), directory,
                          force=force, no_overwrite=no_overwrite, recursive=recursive,
                          exclude_dependencies=exclude_dependencies, update=update,
                          rosdep_urls=rosdep_urls, generated=generated)
  output_directory = os.path.join(directory, package.name)
  if not os.path.exists(output_directory):
    os.mkdir(output_directory)
  if os.path.exists(os.path.join(output_directory, 'PKGBUILD')):
    if no_overwrite:
      return
    if not force and query_yes_no(
      "Directory '%s' already contains a PKGBUILD file. Overwrite?" % (
        output_directory)) == "no":
      return
  pkgbuild_file = os.path.join(output_directory, 'PKGBUILD')
  if update:
    if package.is_same_version(pkgbuild_file):
      print('PKGBUILD for package %s already up-to-date (%s)'
            % (colored(package.name, 'yellow', attrs=['bold']),
               colored(package.version + '-' + package.version_patch, 'white',
                       attrs=['bold'])))
      return
  print('Generating PKGBUILD for package %s (%s)'
        % (colored(package.name, 'green', attrs=['bold']),
           colored(package.version + '-' + package.version_patch, 'white',
                   attrs=['bold'])))
  with open(pkgbuild_file, 'w') as pkgbuild:
    pkgbuild.write(package.generate(exclude_dependencies, rosdep_urls))


def main():
  parser = OptionParser(usage='usage: %prog [options] PACKAGE...')
  parser.add_option('--distro', default='groovy', metavar='distro',
                    help='Select the ROS distro to use.')
  parser.add_option('--list-packages', dest='list_packages', action='store_true',
                    default=False, help='Lists all available packages.')
  parser.add_option('--update-packages', dest='update_packages', action='store_true',
                    default=False, help='Updates all available packages.')
  parser.add_option('--output-directory', metavar='output_directory', default='.',
                    help='The output directory. Packages are put into <output-directory>/<name>')
  default_distro_url = 'https://raw.github.com/ros/rosdistro/master/%s/distribution.yaml'
  parser.add_option(
    '--distro-url', metavar='distro_url', default=default_distro_url,
    help='The URL of the distro description. %s is replaced by the actual distro name')
  default_rosdep_url = 'https://raw.github.com/ros/rosdistro/master/rosdep/%s.yaml'
  parser.add_option(
    '--rosdep-urls', metavar='rosdep_urls',
    default=[default_rosdep_url % 'base', default_rosdep_url % 'python', default_rosdep_url % 'ruby'],
    help='The URLs of the rosdep mapping files.')
  parser.add_option(
    '--exclude-dependencies', metavar='exclude_dependencies',
    default='',
    help='Comma-separated list of (source) package dependencies to exclude from the generated PKGBUILD file.')
  parser.add_option('-f', '--force', dest='force', action='store_true', default=False,
                    help='Always overwrite exiting PKGBUILD files.')
  parser.add_option('-n', '--no-overwrite', dest='no_overwrite', action='store_true', default=False,
                    help='Do not overwrite PKGBUILD files.')
  parser.add_option('-r','--recursive', dest='recursive', action='store_true', default=False,
                    help='Recursively import dependencies')
  parser.add_option('-u','--update', dest='update', action='store_true', default=False,
                    help='Update PKGBUILD if a newer version is found.')
  options, args = parser.parse_args()

  if options.distro == "fuerte" and options.distro_url == default_distro_url:
    # Use legagy fuerte URL
    options.distro_url = 'https://raw.github.com/ros/rosdistro/master/releases/%s.yaml'

  distro = DistroDescription(
    options.distro, url=options.distro_url % options.distro)
  if options.list_packages:
    list_packages(distro)
  elif options.update_packages:
    packages = os.listdir(os.path.abspath(options.output_directory))
    exclude_dependencies = options.exclude_dependencies.split(',')
    for package in packages:
      if package in exclude_dependencies:
        continue
      generate_pkgbuild(distro, distro.package(package),
                        os.path.abspath(options.output_directory),
                        exclude_dependencies=options.exclude_dependencies.split(','),
                        force=options.force, no_overwrite=options.no_overwrite,
                        update=options.update, recursive=options.recursive,
                        rosdep_urls=options.rosdep_urls)
  elif args:
    for package in args:
      generate_pkgbuild(distro, distro.package(package),
                        os.path.abspath(options.output_directory),
                        exclude_dependencies=options.exclude_dependencies.split(','),
                        force=options.force, no_overwrite=options.no_overwrite,
                        update=options.update, recursive=options.recursive,
                        rosdep_urls=options.rosdep_urls)
  else:
    parser.error('No package specified.')


if __name__ == '__main__':
  main()
