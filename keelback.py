"""
Keelback · Static Site Generator
"""


from __future__ import annotations
from datetime import datetime

import pystache
import markdown

import os, pathlib, time, shutil, errno, re
from posixpath import abspath

# Compile quicklink regex now for faster matching
QL = re.compile("(\s|^|\>)\[\[(.+?)\]\](\s|$|\<|[,.;:‘’“”])")


def slugify(_string: str) -> str:
    """
    Convert an arbitrary string to a URL slug. In theory
    this should sanitise the string, replace spaces with
    plusses, etc. In practice it just makes it lowercase.

    Args:
        _string: the string to be slugified.

    Returns:
        A slugified version of the input string.
    """
    punctuation = "\"'.,“”‘’:;()[]\{\}"
    for character in punctuation:
        if character in _string:
            _string = _string.replace(character, "")
    _slug = _string.lower().replace("/", "-").replace(" ", "-")
    return _slug


def parse_quicklinks(_body: str) -> str:
    """
    Extract quick (wikipedia-style) link shorthands, and
    replace them with HTML <a> tags pointing at the page
    to which the link refers.

    Args:
        _body: A page node’s body text (or in theory any
               string) to be parsed.

    Returns:
        The input string, with [[page]]-syntax links replaced
        by functional anchor tags.
    """
    matches = QL.finditer(_body)

    for match in matches:
        quicklink = match.group(2).strip()

        if slugify(quicklink) in pages:
            _body = _body.replace(
                match.group(0),
                match.group(1) + pages[slugify(quicklink)].link + match.group(3),
            )
        else:
            _body = _body.replace(
                match.group(0), match.group(1) + quicklink + match.group(3)
            )

    return _body


class Node:
    """
    Every object in a Keelback project is a Node of some
    kind, though the base Node class should only ever be
    used as a placeholder. By default, every node should
    be either a Category or a Page (both of which extend
    the Node class).
    """

    path: str
    title: str
    slug: str
    children: list[Node] = []

    metadata_delimiter: str = "====="
    template: str = """
    <nav class="crumb">
        {{{ breadcrumb }}}
    </nav>

    <article>
        This page is empty.
    </article>
    """

    def __repr__(self) -> str:
        return "Node: {}".format(self.slug)

    def __init__(self) -> None:
        self._parent: Node = None

    @property
    def parent(self) -> Node:
        return self._parent

    @parent.setter
    def parent(self, new_parent: Node) -> None:
        if new_parent == self:
            if self.title != "Index":
                print(
                    "Can’t set a node’s parent to itself! (node: {})".format(self.title)
                )
        elif new_parent:
            if self._parent:
                if self in self._parent.children:
                    self._parent.children.remove(self)

            new_parent.children.append(self)
            self._parent = new_parent
        else:
            print("Can’t set a node’s parent to None!")

    # @property
    # def slug(self) -> str:
    #     return slugify(self.title)

    @property
    def link(self) -> str:
        return self.get_link()

    def get_link(self, link_text: str = None, highlight: bool = False) -> str:
        """
        Generates an HTML anchor element which links to this
        node, with the element’s text content being either a
        custom input string, or the node title.

        Args:
            link_text: (optional) text for the link.

        Returns:
            A string containing the link HTML element.
        """
        template: str = "<a href='./{slug}.html' {highlight}>{text}</a>"
        link_text: str = link_text if link_text else self.title
        highlight: str = "class='highlit'" if highlight else ""
        return template.format(slug=self.slug, highlight=highlight, text=link_text)

    @property
    def breadcrumb(self) -> str:
        """
        Generates a series of HTML <a> elements representing
        the heirarchical location of this node.

        Returns:
            A string containing multiple HTML links.
        """
        crumb: list[str] = []

        if self.slug != "index":
            pass

        parent: Node = self.parent
        while parent:
            crumb.append(parent.link)
            parent = parent.parent

        crumb.reverse()
        crumb.append(self.get_link(highlight=True))

        return " / ".join(crumb)

    @property
    def context(self) -> dict[any]:
        """
        Returns a dict containing the render context for the
        current node (every variable which may be needed for
        the template renderer).

        Returns:
            A string containing this instance’s render context.
        """
        return dict(
            vars(self),
            breadcrumb=self.breadcrumb,
            pages=pages,
            categories=categories,
        )

    @property
    def html(self) -> str:
        """
        Generates a string of HTML elements according to the
        template for this node.

        Returns:
            A string containing the HTML representation of this node.
        """
        r: pystache.Renderer = pystache.Renderer()
        return r.render(self.template, self.context)

    def assemble(self, layout) -> str:
        """
        Renders this node’s content as a complete HTML file,
        based on a supplied layout template.

        Returns:
            A string representing this node’s HTML document.
        """
        context: dict[any] = self.context
        context["page"] = self.html

        if buildtime:
            context["buildtime"] = buildtime
        if pages:
            context["pages"] = pages
        if categories:
            context["categories"] = categories

        r: pystache.Renderer = pystache.Renderer()

        # Push each node twice through the renderer, so
        # it can have both a local and global context
        first_pass: str = r.render(layout, context)
        return r.render(first_pass, context)


class Page(Node):
    """
    Pages are ‘endpoint’ Nodes containing specific text,
    image, and other content from Markdown source files.
    """

    content: str
    template: str = """
    <nav class="crumb">
        {{{ breadcrumb }}}
    </nav>

    <article>
        {{{ body }}}
    </article>
    """

    def __repr__(self) -> str:
        return "Page node: {}".format(self.slug)

    def __init__(self) -> None:
        self._parent: str = None
        self._title: str = None

    @property
    def title(self) -> str:
        if "title" in self.metadata:
            return self.metadata["title"]
        return self._title

    @title.setter
    def title(self, new_title: str) -> None:
        self._title = new_title

    def split_content(self) -> list[str]:
        """
        Splits this page’s ‘content’ string into two strings
        representing the actual content, in markdown format,
        plus the page’s metadata.

        Returns:
            A list containing the page’s markdown string, and a second
            metadata string if metadata are present.
        """
        if self.content:
            # after reversing, split[0] will *always* be the markdown content
            # split[1] will be the metadata if present, otherwise None
            split: list[str] = self.content.strip().split(self.metadata_delimiter, 1)
            split.reverse()
            return split
        return [""]

    @property
    def markdown(self) -> str:
        """Returns the markdown content for this page."""
        split: list[str] = self.split_content()
        if split:
            return split[0]
        return ""

    @property
    def metadata(self) -> dict[str, str]:
        """Returns a dict containing this page’s metadata."""
        meta_string: str = self.split_content()[1]
        meta_dict: dict[str, str] = {}
        if meta_string:
            line: str
            for line in meta_string.split("\n"):
                if ":" in line:
                    split: list[str] = line.split(":", 1)
                    key: str = split[0].strip()
                    value: str = split[1].strip()
                    meta_dict[key.lower()] = value
            return meta_dict
        return {}

    @property
    def meta(self) -> dict[str, str]:
        """Backwards-compatible alias for 'metadata' property"""
        return self.metadata

    # @property
    # def full_title(self) -> str:
    #     """Returns this page’s title, either from its
    #     filename or (if present) from its metadata."""
    #     if "title" in self.metadata:
    #         return self.metadata["title"]
    #     return self.title

    def get_link(self, link_text: str = None, highlight: bool = False) -> str:
        template: str = "<a href='./{slug}.html' {highlight}>{text}</a>"
        link_text: str = link_text if link_text else self.title
        highlight: str = "class='highlit'" if highlight else ""
        return template.format(slug=self.slug, highlight=highlight, text=link_text)

    def get_timestamp(
        self, as_string: bool = False, as_html: bool = False
    ) -> datetime or str:
        """
        Returns this Page’s date, if present, as either
        a datetime object or a string.
        """
        if "date" in self.metadata:
            dt: datetime = datetime.strptime(self.metadata["date"], "%d-%m-%Y")
            if as_string:
                return dt.strftime("%b %Y")
            elif as_html:
                template: str = "<span class='timestamp'>{}</span>"
                return template.format(dt.strftime("%b %Y"))
            return dt
        if as_string or as_html:
            return ""
        return None

    @property
    def body(self) -> str:
        # First convert the markdown content to HTML
        template: str = markdown.markdown(self.markdown, extensions=["tables"])

        # Then render the HTML with pystache
        # r: pystache.Renderer = pystache.Renderer()
        # return r.render(template, context)

        return parse_quicklinks(template)

    @property
    def context(self) -> dict[any]:
        return dict(
            vars(self),
            title=self.title,
            breadcrumb=self.breadcrumb,
            body=self.body,
            pages=pages,
            categories=categories,
            meta=self.metadata,
        )


class Category(Node):
    """
    Categories are ‘endpoint’ nodes which display a list
    of their child nodes automatically. They’re intended
    to be overwritten by Page nodes in many cases, but a
    Category node will be created automatically if there
    is any node with children but no content of its own.
    """

    template: str = """
    <nav class="crumb">
        {{{ breadcrumb }}}
    </nav>

    <article>
        <h2>Pages in this category:</h2>
        {{{ contents }}}
    </article>
    """

    def __repr__(self) -> str:
        return "Category node: {}".format(self.slug)

    @property
    def contents(self) -> str:
        """
        Returns a string containing an HTML list of links to
        every child node within this category.
        """
        ol: list[str] = ["<ol class='category'>"]
        ul: list[str] = ["<ul class='category'>"]

        if self.children:
            if self.children[0].get_timestamp():
                self.children.sort(
                    key=lambda x: (x.get_timestamp(), x.title), reverse=True
                )
                for node in self.children:
                    li: str = "<li>{link} {timestamp}</li>"
                    ol.append(
                        li.format(
                            link=node.link,
                            timestamp=node.get_timestamp(as_html=True),
                        )
                    )
                return "\n".join(ol)
            else:
                self.children.sort(key=lambda x: x.title, reverse=False)
                for node in self.children:
                    li: str = "<li>{link} {timestamp}</li>"
                    ul.append(
                        li.format(
                            link=node.link,
                            timestamp=node.get_timestamp(as_html=True),
                        )
                    )
                return "\n".join(ul)
        return ""

    @property
    def context(self) -> dict[any]:
        return dict(
            vars(self),
            breadcrumb=self.breadcrumb,
            contents=self.contents,
            pages=pages,
            categories=categories,
        )


def make_node(
    path: str,
    title: str,
    children: list[Node] = [],
    from_file: str = None,
) -> Node:
    """
    Create a new Keelback node somewhere in the tree. It
    can have a single parent, multiple children, and can
    also be generated from a markdown file.

    A node generated from a file will be a Page, while a
    node no content will be a Category (even if it would
    initially have no children).
    """

    if from_file:
        node: Page = Page()
        with open(os.path.join(path, from_file), "r") as f:
            node.content = f.read()
        node.slug = slugify(from_file.split(".", 1)[0])
    else:
        node: Category = Category()
        node.slug = slugify(title)

    node.path = path
    node.title = title
    node.children = children

    return node


def create_nodetree(content_dir: str) -> dict[str, Node]:
    nodetree: dict[str, Node] = {}

    for path, dirs, files in os.walk(content_dir):
        # Create category nodes
        p: pathlib.Path = pathlib.Path(path)
        if str(p.name).lower() != "content":
            new_category: Category = make_node(path, p.name, children=[])
            if str(p.parent.name) in nodetree.keys():
                new_category.parent = nodetree[str(p.parent.name)]
            nodetree[p.name] = new_category

        # Create page nodes
        for file in files:
            if file.endswith(".txt"):
                title: str = file[:-4]

                new_page: Page = make_node(path, title, from_file=file)

                # Upgrade any existing category node to a page
                if new_page.slug in nodetree:
                    category_node: Node = nodetree[new_page.slug]
                    if category_node.parent:
                        new_page.parent = category_node.parent
                    if category_node.children:
                        for child in category_node.children:
                            child.parent = new_page
                        # new_page.children = category_node.children

                nodetree[new_page.slug] = new_page

                if str(p.name).lower() != "content":
                    # i.e. we’re not in the root category
                    if str(p.name) != new_page.slug:
                        if str(p.name) in nodetree.keys():
                            new_page.parent = nodetree[str(p.name)]
                    else:
                        # The new page has the same name as the current dir
                        # (i.e. it’s a category override)
                        if str(p.parent.name) in nodetree.keys():
                            new_page.parent = nodetree[str(p.parent.name)]

    # Set orphan nodes to be children of index
    for node in nodetree.values():
        if not node.parent and node.title != "index":
            node.parent = nodetree["index"]

    return nodetree


def write_node(node: Node, layout: str, export_directory: str) -> None:
    html: str = node.assemble(layout)
    with open(os.path.join(export_directory, node.slug + ".html"), "w") as f:
        f.write(html)


def build_pages(
    nodetree: dict[str, Node], layout_file: str, export_directory: str
) -> None:
    layout: str
    with open(layout_file, "r") as f:
        layout = f.read()

    for node in nodetree.values():
        write_node(node, layout, export_directory)


def tree_clone(source: abspath, destination: abspath):
    try:
        shutil.copytree(source, destination)
    except OSError as e:
        if e.errno == errno.ENOTDIR:
            shutil.copy(source, destination)
        else:
            print("Directory not copied:\n{}".format(str(e)))


def copy_static(source: str, destination: str):
    source = os.path.abspath(os.path.join(source))
    destination = os.path.abspath(destination)
    tree_clone(source, destination)


def build_site(
    content_directory: str,
    static_directory: str,
    layout_file: str,
    export_directory: str,
) -> None:
    start: time.time = time.time()

    print("[KEELBACK]: Cleaning export directory...")
    if os.path.isdir(export_directory):
        shutil.rmtree(os.path.abspath(export_directory))

    if os.path.isdir(static_directory):
        print("[KEELBACK]: Copying static files...")
        copy_static(static_directory, export_directory)
    else:
        os.mkdir(export_directory)

    print("[KEELBACK]: Building Nodetree...")
    nodetree = create_nodetree(content_directory)

    # Expose global variables for use in node render contexts
    global buildtime
    buildtime = datetime.now().strftime("%Y·%m·%d %H:%M")

    global pages, categories
    pages = {}
    categories = {}
    for node in nodetree.values():
        if node.__class__ == Page:
            pages[node.slug] = node
        elif node.__class__ == Category:
            categories[node.slug] = node

    print("[KEELBACK]: Building pages...")
    build_pages(nodetree, layout_file, export_directory)

    stop: time.time = time.time()
    elapsed: int = int((stop - start) * 1000)
    print("[KEELBACK]: Done! ({} ms.)".format(elapsed))
