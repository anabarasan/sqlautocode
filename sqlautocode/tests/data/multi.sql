# multi.sql

create table album(
    albumid int,
    albumname text,
    albumartist text,
    primary key (albumid)
);

create table song(
    songalbum text,
    songartist text,
    songid int,
    songname text,
    primary key (songid),
    constraint fkalbumsongalbum foreign key (songalbum) references album(albumname),
    constraint fkalbumsongartist foreign key(songartist) references album(albumartist)
);
